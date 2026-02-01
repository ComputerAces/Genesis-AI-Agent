import torch
import os
import warnings
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

# Suppress bitsandbytes quantization casting warnings
warnings.filterwarnings("ignore", message=".*MatMul8bitLt: inputs will be cast from torch.bfloat16 to float16.*")

class QwenProvider:
    def __init__(self, model_name="Qwen/Qwen3-0.6B", model_cfg=None, **kwargs):
        self.model_cfg = model_cfg or {}
        device = self.model_cfg.get("device", "auto")
        quantize = self.model_cfg.get("quantize", "int8")
        
        print(f"[INFO] Loading model {model_name} (Quantize: {quantize}, Device: {device})...")
        
        # Robust loading with offline fallback
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        except (OSError, ValueError, Exception) as e:
            print(f"[WARN] Connection error ({str(e)}). Attempting to load Tokenizer in offline mode...")
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
            except Exception as e2:
                print(f"[FATAL] Could not load Tokenizer locally either: {e2}")
                raise e2
        
        # Create offload folder if it doesn't exist
        offload_dir = "model_offload"
        if not os.path.exists(offload_dir):
            os.makedirs(offload_dir)

        # Config quantization based on settings
        quantization_config = None
        if quantize == "int8":
            from transformers import BitsAndBytesConfig
            quantization_config = BitsAndBytesConfig(load_in_8bit=True)
        elif quantize == "int4":
            from transformers import BitsAndBytesConfig
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True
            )

        # Apply rope_scaling if use_yarn is enabled
        use_yarn = self.model_cfg.get("use_yarn")
        rope_scaling = None
        if use_yarn:
            # Auto-YaRN: Default to 4.0 factor if enabled
            # Note: newer transformers (4.51+) uses 'rope_type' instead of 'type'
            # Qwen3-0.6B base context is 32768, theta is usually 1000000
            rope_scaling = {
                "rope_type": "yarn", 
                "factor": 4.0,
                "original_max_position_embeddings": 32768,
                "rope_theta": 1000000.0
            }
        
        load_kwargs = {
            "torch_dtype": "auto",
            "device_map": device,
            "quantization_config": quantization_config,
            "offload_folder": offload_dir,
            "offload_state_dict": True
        }
        
        if rope_scaling:
            load_kwargs["rope_scaling"] = rope_scaling

        try:
            self.model = AutoModelForCausalLM.from_pretrained(model_name, **load_kwargs)
        except (OSError, ValueError, Exception) as e:
            print(f"[WARN] Connection error ({str(e)}). Attempting to load Model in offline mode...")
            try:
                self.model = AutoModelForCausalLM.from_pretrained(model_name, local_files_only=True, **load_kwargs)
            except Exception as e2:
                print(f"[FATAL] Could not load Model locally either: {e2}")
                raise e2

        self.device = self.model.device

    def generate(self, prompt, use_thinking=True, stop_event=None, return_json=False, parent_id="default", history_override=None, system_prompt=None):
        # Use provided history (from DB)
        if history_override is not None:
            history = list(history_override)
        else:
            # Fallback if somehow missing
            history = [{"role": "user", "content": prompt}]
        
        # Ensure latest prompt is in history if not already there
        if not history or history[-1]["content"] != prompt:
            history.append({"role": "user", "content": prompt})

        # Inject System Prompt transiently for the model template
        # This ensures it guides generation but isn't part of the persistent 'history' list
        template_history = []
        if system_prompt:
            template_history.append({"role": "system", "content": system_prompt})
        
        template_history.extend(history)

        # Apply chat template
        text = self.tokenizer.apply_chat_template(
            template_history,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=use_thinking
        )

        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=False)

        # Sampling parameters
        sampling_cfg = self.model_cfg.get("sampling", {})
        profile = "thinking" if use_thinking else "normal"
        params = sampling_cfg.get(profile, {})
        
        gen_kwargs = {
            "temperature": params.get("temperature", 0.6 if use_thinking else 0.7),
            "top_p": params.get("top_p", 0.95 if use_thinking else 0.8),
            "top_k": params.get("top_k", 20),
            "min_p": params.get("min_p", 0.0),
            "max_new_tokens": self.model_cfg.get("output_size", 32768),
            "streamer": streamer,
            "do_sample": True,
            "use_cache": True  # Enable KV Caching explicitly
        }

        # Run generation in a separate thread
        from threading import Thread
        thread = Thread(target=self.model.generate, kwargs={**model_inputs, **gen_kwargs})
        thread.start()

        full_response_text = ""
        is_thinking = use_thinking
        has_started_thinking = False
        THINK_START_TOKEN = "<think>"
        THINK_END_TOKEN = "</think>"
        
        for new_text in streamer:
            if stop_event and stop_event.is_set():
                break
            
            full_response_text += new_text
            chunk_to_yield = new_text

            # State Machine for Tag Parsing
            if is_thinking:
                # Check for start token if we haven't seen it (though strictly Qwen starts with it)
                if THINK_START_TOKEN in chunk_to_yield and not has_started_thinking:
                    has_started_thinking = True
                    chunk_to_yield = chunk_to_yield.replace(THINK_START_TOKEN, "")
                
                # Check for end token
                if THINK_END_TOKEN in chunk_to_yield:
                    parts = chunk_to_yield.split(THINK_END_TOKEN)
                    think_part = parts[0]
                    content_part = parts[1] if len(parts) > 1 else ""
                    
                    if think_part:
                        yield {"status": "thinking", "chunk": think_part}
                    
                    is_thinking = False
                    # We don't have the "full" accumulated thinking here easily without reconstructing
                    # But core.py accumulates it too. We can yield a "finished" signal.
                    # For consistency with core.py expecting full thinking in "thinking_finished":
                    # We can reconstruct it from full_response_text or just let core handle accumulation.
                    # Let's EXTRACT it from full_response key for safety in the finished event.
                    
                    # Calculate total thinking so far for the finished event
                    total_think = full_response_text.split(THINK_END_TOKEN)[0].replace(THINK_START_TOKEN, "").strip()
                    yield {"status": "thinking_finished", "thinking": total_think}
                    
                    if content_part:
                        yield {"status": "content", "chunk": content_part}
                else:
                    # Normal thinking chunk
                    # Filter out <think> if it appears (handled above in start check, but just in case)
                    chunk_to_yield = chunk_to_yield.replace(THINK_START_TOKEN, "")
                    if chunk_to_yield:
                         yield {"status": "thinking", "chunk": chunk_to_yield}
            else:
                # Content Mode
                # Use replace just in case of stray tags, though unlikely
                chunk_to_yield = chunk_to_yield.replace(THINK_END_TOKEN, "")
                if chunk_to_yield:
                    yield {"status": "content", "chunk": chunk_to_yield}

        thread.join()

        # Update Token Usage
        input_tokens = model_inputs["input_ids"].shape[1]
        output_tokens = len(self.tokenizer.encode(full_response_text))
        
        from modules.config import update_token_usage
        update_token_usage(self.model_cfg.get("id", "Qwen/Qwen3-0.6B"), input_tokens, output_tokens)

    def clear_history(self, parent_id=None):
        # Database history is handled in AIAgent.clear_history
        pass

    def get_history(self, parent_id=None):
        # Database history is handled in AIAgent.get_history
        return []
