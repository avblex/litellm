import json
from pathlib import Path
from typing import Final

import litellm

_TOKENIZER_SPEC: Final = json.loads(Path(__file__).parent.joinpath("tokenizer.json").read_text(encoding="utf-8"))
_TOKENIZER_SPEC["truncation"] = None

_QWEN_TOKENIZER: Final = litellm.create_tokenizer(json.dumps(_TOKENIZER_SPEC))

_original_token_counter: Final = litellm.token_counter


def token_counter(*args, **kwargs):
    kwargs.setdefault("custom_tokenizer", _QWEN_TOKENIZER)
    return _original_token_counter(*args, **kwargs)


litellm.token_counter = token_counter


class _StartupImportHook(litellm.CustomLogger):
    pass


_loader_instance: Final = _StartupImportHook()
