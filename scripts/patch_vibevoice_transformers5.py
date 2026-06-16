"""Patch vibevoice==0.0.1 for compatibility with transformers>=5.x.

vibevoice 0.0.1 was built against transformers==4.51.3. Running it against
transformers 5.x (which hevi venv uses via Python 3.14) requires 12 patches.

Usage:
    python scripts/patch_vibevoice_transformers5.py [venv_dir]

If venv_dir is omitted, uses the `.venv` in the current directory.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def site_packages(venv: Path) -> Path:
    for p in sorted(venv.glob("lib/python*/site-packages"), reverse=True):
        return p
    raise FileNotFoundError(f"No site-packages found under {venv}")


def patch(path: Path, old: str, new: str, label: str) -> bool:
    text = path.read_text()
    if new.strip() in text:
        print(f"  [SKIP] {label} — already patched")
        return False
    if old not in text:
        print(f"  [WARN] {label} — old pattern not found, skipping")
        return False
    path.write_text(text.replace(old, new, 1))
    print(f"  [OK]   {label}")
    return True


def main(venv_dir: str | None = None) -> None:
    venv = Path(venv_dir or ".venv").resolve()
    sp = site_packages(venv)
    vv = sp / "vibevoice"
    if not vv.exists():
        print(f"ERROR: vibevoice not installed in {sp}")
        sys.exit(1)

    print(f"Patching vibevoice in: {vv}")
    modular = vv / "modular"

    # ── Patch 1: exist_ok in modular_vibevoice_tokenizer.py ─────────────────
    patch(
        modular / "modular_vibevoice_tokenizer.py",
        "AutoModel.register(VibeVoiceAcousticTokenizerConfig, VibeVoiceAcousticTokenizerModel)\n"
        "AutoModel.register(VibeVoiceSemanticTokenizerConfig, VibeVoiceSemanticTokenizerModel)",
        "AutoModel.register(VibeVoiceAcousticTokenizerConfig, VibeVoiceAcousticTokenizerModel, exist_ok=True)\n"
        "AutoModel.register(VibeVoiceSemanticTokenizerConfig, VibeVoiceSemanticTokenizerModel, exist_ok=True)",
        "P1: AutoModel.register exist_ok=True (transformers 5.x already has vibevoice built-in)",
    )

    # ── Patch 2: Qwen2TokenizerFast missing in transformers 5.x ─────────────
    patch(
        modular / "modular_vibevoice_text_tokenizer.py",
        "from transformers.models.qwen2.tokenization_qwen2_fast import Qwen2TokenizerFast",
        "try:\n"
        "    from transformers.models.qwen2.tokenization_qwen2_fast import Qwen2TokenizerFast\n"
        "except ImportError:\n"
        "    Qwen2TokenizerFast = Qwen2Tokenizer",
        "P2: Qwen2TokenizerFast fallback (removed in transformers 5.x)",
    )

    # ── Patch 3a/3b: dpm_solver.py is_meta guard for __init__ ───────────────
    dpm = vv / "schedule" / "dpm_solver.py"
    dpm_text = dpm.read_text()
    # Two .to("cpu") calls in __init__ that blow up on meta tensors
    new_dpm = dpm_text.replace(
        'self.sigmas = self.sigmas.to("cpu")  # to avoid too much CPU/GPU communication',
        'if not self.sigmas.is_meta:  # skip on meta device (transformers 5.x from_pretrained context)\n'
        '            self.sigmas = self.sigmas.to("cpu")  # to avoid too much CPU/GPU communication',
    )
    if new_dpm != dpm_text:
        dpm.write_text(new_dpm)
        print("  [OK]   P3: dpm_solver is_meta guard for sigmas.to('cpu')")
    else:
        print("  [SKIP] P3: dpm_solver is_meta guard — already patched or not found")

    # ── Patch 4: dpm_solver set_timesteps reinit if lambda_t is meta ─────────
    patch(
        dpm,
        "        if num_inference_steps is None and timesteps is None:\n"
        "            raise ValueError(\"Must pass exactly one of `num_inference_steps` or `timesteps`.\")\n"
        "        if num_inference_steps is not None and timesteps is not None:\n"
        "            raise ValueError(\"Can only pass one of `num_inference_steps` or `custom_timesteps`.\")",
        "        # transformers 5.x from_pretrained leaves scheduler tensors on meta device; reinit with saved config\n"
        "        if self.lambda_t.is_meta:\n"
        "            self.__class__.__init__(self, **{k: v for k, v in self.config.items()})\n\n"
        "        if num_inference_steps is None and timesteps is None:\n"
        "            raise ValueError(\"Must pass exactly one of `num_inference_steps` or `timesteps`.\")\n"
        "        if num_inference_steps is not None and timesteps is not None:\n"
        "            raise ValueError(\"Can only pass one of `num_inference_steps` or `custom_timesteps`.\")",
        "P4: dpm_solver set_timesteps reinit if lambda_t still on meta device",
    )

    inf = modular / "modeling_vibevoice_inference.py"

    # ── Patch 5: tie_weights **kwargs ─────────────────────────────────────────
    patch(
        inf,
        "    def tie_weights(self):",
        "    def tie_weights(self, **kwargs):",
        "P5: tie_weights **kwargs (transformers 5.x passes recompute_mapping=False)",
    )

    # ── Patch 6: tie_weights check decoder_config.tie_word_embeddings ─────────
    patch(
        inf,
        "        if not getattr(self.config, 'tie_word_embeddings', False):\n"
        "            return\n"
        "         \n"
        "        if hasattr(self, 'lm_head') and hasattr(self.model.language_model, 'embed_tokens'):\n"
        "            self.lm_head.weight = self.model.language_model.embed_tokens.weight",
        "        # Check top-level config first, then decoder_config (transformers 5.x uses top-level only)\n"
        "        tie = getattr(self.config, 'tie_word_embeddings', None)\n"
        "        if tie is None:\n"
        "            tie = getattr(getattr(self.config, 'decoder_config', None), 'tie_word_embeddings', False)\n"
        "        if not tie:\n"
        "            return\n\n"
        "        if hasattr(self, 'lm_head') and hasattr(self.model.language_model, 'embed_tokens'):\n"
        "            self.lm_head.weight = self.model.language_model.embed_tokens.weight",
        "P6: tie_weights fallback to decoder_config.tie_word_embeddings (VibeVoiceConfig top-level is None)",
    )

    # ── Patch 7: _prepare_generation_config remove True positional arg ────────
    patch(
        inf,
        "        generation_config, model_kwargs = self._prepare_generation_config(\n"
        "            generation_config, \n"
        "            True, \n"
        "            speech_start_id=tokenizer.speech_start_id, ",
        "        generation_config, model_kwargs = self._prepare_generation_config(\n"
        "            generation_config,\n"
        "            # True was 'use_model_defaults' positional arg in transformers 4.51; removed in 5.x\n"
        "            speech_start_id=tokenizer.speech_start_id, ",
        "P7: _prepare_generation_config remove True positional arg (removed in transformers 5.x)",
    )

    # ── Patch 8: _prepare_cache_for_generation remove device arg ─────────────
    patch(
        inf,
        "        self._prepare_cache_for_generation(generation_config, model_kwargs, None, batch_size, max_cache_length, device)",
        "        self._prepare_cache_for_generation(generation_config, model_kwargs, None, batch_size, max_cache_length)",
        "P8: _prepare_cache_for_generation remove device arg (removed in transformers 5.x)",
    )

    # ── Patch 9: VibeVoiceConfig num_hidden_layers + get_text_config ─────────
    cfg = modular / "configuration_vibevoice.py"
    patch(
        cfg,
        "        super().__init__(**kwargs)\n\n__all__",
        "        super().__init__(**kwargs)\n\n"
        "    @property\n"
        "    def num_hidden_layers(self) -> int:\n"
        "        # transformers 5.x DynamicCache expects this on the top-level config\n"
        "        return self.decoder_config.num_hidden_layers\n\n"
        "    def get_text_config(self, decoder=None, encoder=None):\n"
        "        # transformers 5.x composite-config hook: always return the LLM sub-config\n"
        "        return self.decoder_config\n\n__all__",
        "P9: VibeVoiceConfig num_hidden_layers property + get_text_config (transformers 5.x DynamicCache)",
    )

    # ── Patch 10: speech_tensors None guard (prefill) ─────────────────────────
    patch(
        inf,
        "            if is_prefill:\n"
        "                # we process the speech inputs only during the first generation step\n"
        "                prefill_inputs = {\n"
        "                    \"speech_tensors\": speech_tensors.to(device=device),\n"
        "                    \"speech_masks\": speech_masks.to(device),\n"
        "                    \"speech_input_mask\": speech_input_mask.to(device),\n"
        "                }\n"
        "                is_prefill = False",
        "            if is_prefill:\n"
        "                # we process the speech inputs only during the first generation step\n"
        "                if speech_tensors is not None:\n"
        "                    prefill_inputs = {\n"
        "                        \"speech_tensors\": speech_tensors.to(device=device),\n"
        "                        \"speech_masks\": speech_masks.to(device),\n"
        "                        \"speech_input_mask\": speech_input_mask.to(device),\n"
        "                    }\n"
        "                else:\n"
        "                    prefill_inputs = {}\n"
        "                is_prefill = False",
        "P10: speech_tensors None guard (no voice_ref means None speech tensors)",
    )

    # ── Patch 11: key_cache → layers compat (speech_begin block) ─────────────
    patch(
        inf,
        "                for layer_idx, (k_cache, v_cache) in enumerate(zip(negative_model_kwargs['past_key_values'].key_cache, \n"
        "                                                                        negative_model_kwargs['past_key_values'].value_cache)):\n"
        "                    # Process each non-diffusion sample\n"
        "                    for sample_idx in diffusion_start_indices.tolist():",
        "                _pkv = negative_model_kwargs['past_key_values']\n"
        "                _layers = list(zip(_pkv.key_cache, _pkv.value_cache)) if hasattr(_pkv, 'key_cache') else [(l.keys, l.values) for l in _pkv.layers if l.keys is not None]\n"
        "                for layer_idx, (k_cache, v_cache) in enumerate(_layers):\n"
        "                    # Process each non-diffusion sample\n"
        "                    for sample_idx in diffusion_start_indices.tolist():",
        "P11a: DynamicCache key_cache/value_cache → layers compat (speech_begin block)",
    )
    patch(
        inf,
        "                    for layer_idx, (k_cache, v_cache) in enumerate(zip(negative_model_kwargs['past_key_values'].key_cache, \n"
        "                                                                        negative_model_kwargs['past_key_values'].value_cache)):\n"
        "                        # Process each non-diffusion sample\n"
        "                        for sample_idx, start_idx in zip(non_diffusion_indices.tolist(), start_indices.tolist()):",
        "                    _pkv2 = negative_model_kwargs['past_key_values']\n"
        "                    _layers2 = list(zip(_pkv2.key_cache, _pkv2.value_cache)) if hasattr(_pkv2, 'key_cache') else [(l.keys, l.values) for l in _pkv2.layers if l.keys is not None]\n"
        "                    for layer_idx, (k_cache, v_cache) in enumerate(_layers2):\n"
        "                        # Process each non-diffusion sample\n"
        "                        for sample_idx, start_idx in zip(non_diffusion_indices.tolist(), start_indices.tolist()):",
        "P11b: DynamicCache key_cache/value_cache → layers compat (non-diffusion shift block)",
    )

    # ── Patch 12: inputs_embeds KeyError → .get() ────────────────────────────
    patch(
        inf,
        "                    if negative_model_inputs['inputs_embeds'] is None and inputs_embeds is not None:",
        "                    if negative_model_inputs.get('inputs_embeds') is None and inputs_embeds is not None:",
        "P12: negative_model_inputs.get() instead of [] (inputs_embeds not always in dict in transformers 5.x)",
    )

    print("\nDone. All patches applied (or already present).")
    print("Required packages: diffusers accelerate librosa numba ml-collections absl-py")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
