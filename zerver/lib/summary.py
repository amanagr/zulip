from zerver.lib.narrow import  NarrowParameter
from django.conf import settings
import os

import litellm
from litellm import completion

if settings.HUGGING_FACE_API_KEY:
    litellm.huggingface_key = settings.HUGGING_FACE_API_KEY

def generate_summary(narrow: list[NarrowParameter]) -> str:
    
