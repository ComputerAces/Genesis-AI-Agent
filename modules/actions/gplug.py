"""
Genesis .gplug Ecosystem
========================
Handles plugin packaging, installation, and integrity verification.

.gplug files are ZIP archives containing:
- manifest.json (required)
- main.py or other scripts
- requirements.txt (optional)
- Any additional plugin files
"""
import os
import json
import zipfile
import hashlib
import tempfile
import shutil
from typing import Dict, Optional, Tuple
from datetime import datetime


def calculate_manifest_hash(manifest: Dict) -> str:
    """
    Calculate SHA-256 hash of manifest content for integrity verification.
    Excludes the 'integrity' field itself from the hash calculation.
    """
    # Create copy without integrity field
    manifest_copy = {k: v for k, v in manifest.items() if k != 'integrity'}
    manifest_str = json.dumps(manifest_copy, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(manifest_str.encode('utf-8')).hexdigest()


def sign_manifest(manifest: Dict) -> Dict:
    """
    Sign a manifest by adding an integrity hash.
    Returns the manifest with 'integrity' field added.
    """
    manifest_hash = calculate_manifest_hash(manifest)
    manifest['integrity'] = {
        'sha256': manifest_hash,
        'signed_at': datetime.now().isoformat()
    }
    return manifest


def verify_manifest(manifest: Dict) -> Tuple[bool, str]:
    """
    Verify manifest integrity against stored hash.
    
    Returns:
        (is_valid, message)
    """
    if 'integrity' not in manifest:
        return True, "No integrity lock (unverified plugin)"
    
    stored_hash = manifest['integrity'].get('sha256')
    if not stored_hash:
        return False, "Invalid integrity block: missing sha256"
    
    calculated_hash = calculate_manifest_hash(manifest)
    
    if calculated_hash == stored_hash:
        return True, "Integrity verified"
    else:
        return False, f"Integrity mismatch: expected {stored_hash[:16]}..., got {calculated_hash[:16]}..."


def pack_plugin(plugin_path: str, output_path: str = None) -> str:
    """
    Pack a plugin folder into a .gplug file.
    
    Args:
        plugin_path: Path to plugin folder (must contain manifest.json)
        output_path: Optional output path. Defaults to plugin_path + '.gplug'
    
    Returns:
        Path to the created .gplug file
    
    Raises:
        ValueError: If manifest.json not found or invalid
    """
    plugin_path = os.path.abspath(plugin_path)
    manifest_path = os.path.join(plugin_path, 'manifest.json')
    
    if not os.path.exists(manifest_path):
        raise ValueError(f"No manifest.json found in {plugin_path}")
    
    # Load and sign manifest
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    # Sign the manifest
    signed_manifest = sign_manifest(manifest)
    
    # Temporarily update manifest with signature
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(signed_manifest, f, indent=2)
    
    try:
        # Determine output path
        if output_path is None:
            plugin_name = manifest.get('id', os.path.basename(plugin_path))
            output_path = os.path.join(os.path.dirname(plugin_path), f"{plugin_name}.gplug")
        
        # Create ZIP archive
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(plugin_path):
                # Skip __pycache__ and .venv directories
                dirs[:] = [d for d in dirs if d not in ('__pycache__', '.venv', 'venv', '.git')]
                
                for file in files:
                    if file.endswith('.pyc'):
                        continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, plugin_path)
                    zf.write(file_path, arcname)
        
        return output_path
    
    finally:
        # Restore original manifest (without signature if it wasn't there)
        # Actually, we want to keep the signature, so don't restore
        pass


def unpack_plugin(gplug_path: str, target_dir: str, verify: bool = True) -> Dict:
    """
    Unpack a .gplug file to target directory.
    
    Args:
        gplug_path: Path to .gplug file
        target_dir: Target directory to extract to
        verify: Whether to verify integrity after extraction
    
    Returns:
        The manifest dict from the plugin
    
    Raises:
        ValueError: If archive invalid or integrity check fails
    """
    if not os.path.exists(gplug_path):
        raise ValueError(f"File not found: {gplug_path}")
    
    if not zipfile.is_zipfile(gplug_path):
        raise ValueError(f"Invalid .gplug file (not a ZIP archive): {gplug_path}")
    
    # Extract to temp dir first for validation
    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(gplug_path, 'r') as zf:
            zf.extractall(temp_dir)
        
        # Find manifest
        manifest_path = os.path.join(temp_dir, 'manifest.json')
        if not os.path.exists(manifest_path):
            raise ValueError("Invalid .gplug: no manifest.json found")
        
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        # Verify integrity if requested
        if verify:
            is_valid, message = verify_manifest(manifest)
            if not is_valid:
                raise ValueError(f"Integrity check failed: {message}")
        
        # Determine final target path
        plugin_id = manifest.get('id', 'unknown_plugin')
        final_path = os.path.join(target_dir, plugin_id)
        
        # Remove existing if present
        if os.path.exists(final_path):
            shutil.rmtree(final_path)
        
        # Move from temp to final location
        shutil.move(temp_dir, final_path)
        
        # Re-extract manifest since we moved the dir
        manifest_path = os.path.join(final_path, 'manifest.json')
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        manifest['_path'] = final_path
        return manifest


def get_plugin_info(gplug_path: str) -> Dict:
    """
    Get manifest info from a .gplug without extracting.
    """
    if not zipfile.is_zipfile(gplug_path):
        raise ValueError(f"Invalid .gplug file: {gplug_path}")
    
    with zipfile.ZipFile(gplug_path, 'r') as zf:
        try:
            with zf.open('manifest.json') as mf:
                manifest = json.load(mf)
                is_valid, integrity_msg = verify_manifest(manifest)
                manifest['_integrity_status'] = integrity_msg
                manifest['_integrity_valid'] = is_valid
                return manifest
        except KeyError:
            raise ValueError("Invalid .gplug: no manifest.json found")
