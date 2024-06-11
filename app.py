import os
import gc
import json

from typing import Optional

import torch
import numpy as np
from PIL import Image

from pydantic import BaseModel, HttpUrl, Field
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Response, HTTPException

from model.staging import Staging
from helper_func import decode_base64_image, image_to_base64

from diffusers.utils import load_image
from utils import set_img_dims

# Initialise model
MODEL = None
MODEL_NAME = "staging"


# ===============================================================
# App
# ===============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    global MODEL
    MODEL = Staging()
    
    yield
    # Clean up the ML models and release the resources
    flush()


app = FastAPI(lifespan=lifespan)


class RoomRequest(BaseModel):
    image_url: HttpUrl
    room_type: str


@app.get(f'/health')
def get_helath():
    
    return Response(
        content=json.dumps({'health_status': 'ok'}),
        status_code=200
    )

# ===============================================================
# Helpers
# ===============================================================

def flush():
    gc.collect()
    torch.cuda.empty_cache()

# Define the input data model
class TextRequest(BaseModel):
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    num_images_per_prompt: int = 1
    num_inference_steps: int = 30
    guidance_scale: float = 5.0
    seed: int = -1
    width: Optional[int] = None
    height: Optional[int] = None
    padding_factor: float = 5.0
    blur_factor: float = 5.0
    controlnet: Optional[str] = None

def cast_to(data, cast_type):
    try:
        return cast_type(data)
    except Exception as e:
        raise RuntimeError(f"Could not cast {data} to {str(cast_type)}: {e}")

def _stage(response):
    print(response.keys())

    if response.get('image_url'):
        starting_image = response['image_url']
        image = load_image(starting_image).convert("RGB")
    else:
        starting_image = response['image']
        image = decode_base64_image(starting_image)

    # Set random seed if not provided
    if response['seed'] is None:
        response['seed'] = int.from_bytes(os.urandom(2), "big")
    
    # Adjust image dimensions
    image = set_img_dims(image)

    
    # Extract parameters from job input
    prompt = response.get("prompt", None)
    negative_prompt = response.get("negative_prompt", None)
    room_type = response.get("room_type", "bedroom")
    num_images_per_prompt = response.get("num_images", 1)
    print(response["num_inference_steps"])
    num_inference_steps = response.get("num_inference_steps", 35)
    guidance_scale = response.get("guidance_scale", 5)
    seed = response.get("seed", -1)
    width = response.get('width', None)
    height = response.get('height', None)
    padding_factor = response.get('mask_padding', 5)
    blur_factor = response.get('blur_factor', 5)
    controlnet = response.get("controlnet", "mlsd")
    
    # Generate image and mask using the model
    output, mask, control_condition_image = MODEL(
        prompt=prompt,
        negative_prompt=negative_prompt,
        room_type=room_type,
        image=image,
        controlnet=controlnet,
        num_images_per_prompt=num_images_per_prompt,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        width=width,
        height=height,
        seed=seed,
        padding_factor=padding_factor,
        blur_factor=blur_factor
    )

    # Encode output images to base64
    image_strings = []
    output.images[0].save('image.jpg')
    for img in output.images:
        if not isinstance(img, np.ndarray):
            output_image = np.array(img)
        image_strings.append(image_to_base64(output_image))

    # Encode mask to base64
    if not isinstance(mask, np.ndarray):
        mask_image = np.array(mask)
    Image.fromarray(mask_image).save('mask.jpg')
    mask_image = image_to_base64(mask_image)

    # Encode mask to base64
    if not isinstance(control_condition_image, np.ndarray):
        control_condition_image = np.array(control_condition_image)    
    Image.fromarray(control_condition_image).save('control.jpg')
    control_condition_image = image_to_base64(control_condition_image)
    
    # Prepare results dictionary
    results = {
        "result": image_strings[0],
        "mask": mask_image,
        "control_condition_image": control_condition_image,
        "seed": response['seed']
    }


    return results

@app.post("/process")
async def process_image(room_request: TextRequest,
                        image_url: str = Query(..., title="Image URL", description="URL of the image to process"),
                        room_type: str = Query(..., title="Room Type", description="Type of the room")):
    try:
        # Process the image URL and room type as needed
        response = {
            "image_url": image_url,
            "room_type": room_type,
            "prompt": room_request.prompt,
            "negative_prompt": room_request.negative_prompt,
            "num_images_per_prompt": room_request.num_images_per_prompt,
            "num_inference_steps": room_request.num_inference_steps,
            "guidance_scale": room_request.guidance_scale,
            "seed": room_request.seed,
            "width": room_request.width,
            "height": room_request.height,
            "padding_factor": room_request.padding_factor,
            "blur_factor": room_request.blur_factor
        }
        
        response = _stage(response)
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))