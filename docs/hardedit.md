# How to Hard-Edit Genesis to Add Models

While Genesis is designed to be evolved by AI using Antigravity, you can also add new model support manually (the "Old Fashioned Way").

## 1. Create a Provider

Navigate to `modules/ai_agent/providers/` and create a new python file (e.g., `openai_provider.py`).

Your class needs to implement a `generate` method:

```python
class OpenAIProvider:
    def __init__(self, model_name, model_cfg, **kwargs):
        self.model_name = model_name
        self.cfg = model_cfg
        # Initialize client here
        
    def generate(self, prompt, system_prompt=None, history=None, **kwargs):
        # Call API
        # Return text response
        return "Response from OpenAI"
```

## 2. Register in Core

Open `modules/ai_agent/core.py`.

1. Import your new class:

   ```python
   from .providers.openai_provider import OpenAIProvider
   ```

2. Update `__init__` logic (around line 23):

   ```python
   provider_type = self.model_cfg.get("type", "qwen")
   
   if provider_type == "qwen":
       self.provider = QwenProvider(...)
   elif provider_type == "openai":
       self.provider = OpenAIProvider(...)
   ```

## 3. Update Settings

Edit `data/settings.json` to use your new type:

```json
{
  "active_model": {
    "type": "openai",
    "name": "gpt-4o"
  }
}
```

## The "Easy" Way (Antigravity)

If this seems tedious, just tell Antigravity:
*"Add support for OpenAI models."*
It will do all of this for you.
