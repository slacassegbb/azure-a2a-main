#!/usr/bin/env python
# coding: utf-8

import os
from tenacity import retry, wait_random_exponential, stop_after_attempt 
import shutil  
import json
import platform
import re
import requests
import fitz
from PIL import Image
from functools import lru_cache

# Azure OpenAI
from openai import AzureOpenAI
import io
import base64
import pathlib

# Image extraction from PDF
from pathlib import Path  
import uuid

# For LibreOffice Doc Conversion to PDF
import subprocess

# Azure OpenAI configuration for image processing is now sourced from environment variables
_GPT_ENV_VARS = {
    "AZURE_OPENAI_GPT_API_BASE": "Base URL for the Azure AI Foundry project (e.g. https://<host>/api/projects/<project>)",
    "AZURE_OPENAI_GPT_API_KEY": "API key used to access the Azure AI Foundry project",
    "AZURE_OPENAI_GPT_API_VERSION": "API version for the Azure OpenAI deployment",
    "AZURE_OPENAI_GPT_DEPLOYMENT": "Name of the Azure OpenAI deployment to target (e.g. gpt-4o)",
}


@lru_cache(maxsize=1)
def _load_gpt_configuration() -> dict:
    """Load GPT configuration from environment variables once."""
    missing = [name for name in _GPT_ENV_VARS if not os.getenv(name)]
    if missing:
        pretty = ", ".join(missing)
        raise RuntimeError(
            "Missing required environment variables for Azure OpenAI document processing: "
            f"{pretty}. Please set them in your root .env (or environment) so document "
            "processing can extract markdown from images."
        )

    config = {name: os.getenv(name) for name in _GPT_ENV_VARS}

    # Basic logging so we can confirm which deployment is in use without exposing secrets.
    print('Azure OpenAI GPT Base URL:', config["AZURE_OPENAI_GPT_API_BASE"])
    print('Azure OpenAI GPT Deployment:', config["AZURE_OPENAI_GPT_DEPLOYMENT"])

    return config


@lru_cache(maxsize=1)
def _get_gpt_client() -> AzureOpenAI:
    """Instantiate the Azure OpenAI client once using environment configuration."""
    config = _load_gpt_configuration()
    base_url = config["AZURE_OPENAI_GPT_API_BASE"].rstrip("/")

    return AzureOpenAI(
        api_key=config["AZURE_OPENAI_GPT_API_KEY"],  
        api_version=config["AZURE_OPENAI_GPT_API_VERSION"],
        base_url=f"{base_url}/openai/deployments/{config['AZURE_OPENAI_GPT_DEPLOYMENT']}"
    )


def _get_gpt_deployment_name() -> str:
    return _load_gpt_configuration()["AZURE_OPENAI_GPT_DEPLOYMENT"]


supported_conversion_types = ['.pptx', '.ppt', '.docx', '.doc', '.xlsx', '.xls', '.pdf']

# Create directory if it does not exist
def ensure_directory_exists(directory_path):  
    path = Path(directory_path)  
    if not path.exists():  
        path.mkdir(parents=True, exist_ok=True)  
        print(f"Directory created: {directory_path}")  
    else:  
        print(f"Directory already exists: {directory_path}")  
  
# Remove a dir and sub-dirs
def remove_directory(directory_path):  
    try:  
        if os.path.exists(directory_path):  
            shutil.rmtree(directory_path)  
            print(f"Directory '{directory_path}' has been removed successfully.")  
        else:  
            print(f"Directory '{directory_path}' does not exist.")  
    except Exception as e:  
        print(f"An error occurred while removing the directory: {e}")  
    
# Convert to PDF
def convert_to_pdf(input_path):  
    file_suffix = pathlib.Path(input_path).suffix.lower()
    
    if file_suffix in supported_conversion_types:
        ensure_directory_exists('pdf')  
        
        # Extract just the filename (not path) to avoid issues with absolute paths
        base_filename = os.path.basename(input_path)
        filename_no_ext = os.path.splitext(base_filename)[0]
        output_file = os.path.join('pdf', filename_no_ext + '.pdf')
    
        print('Converting', input_path, 'to', output_file)
        if os.path.exists(output_file):
            os.remove(output_file)
    
        if file_suffix == '.pdf':
            # No need to convert, just copy
            shutil.copy(input_path, output_file)  
        else:
            # Set the correct path to soffice based on OS
            if platform.system() == 'Darwin':  # macOS
                soffice_path = '/Applications/LibreOffice.app/Contents/MacOS/soffice'
            else:
                soffice_path = 'soffice'  # Windows/Linux can use just 'soffice'
                
            # Command to convert to pdf using LibreOffice  
            command = [  
                soffice_path,
                '--headless',  # Run LibreOffice in headless mode (no GUI)  
                '--convert-to', 'pdf',  # Specify conversion format  
                '--outdir', os.path.dirname(output_file),  # Output directory  
                input_path  # Input file  
            ]  
              
            try:
                # Run the command  
                subprocess.run(command, check=True)  
                print(f"Conversion complete: {output_file}")
            except subprocess.CalledProcessError as e:
                print(f"Error converting file: {e}")
                return ""
            except FileNotFoundError:
                print("LibreOffice not found. Please ensure LibreOffice is installed and the path is correct.")
                return ""
    else:
        print('File type not supported.')  
        return ""
    
    return output_file

# Convert pages from PDF to images
def extract_pdf_pages_to_images(pdf_path, image_dir):
    # Validate image_out directory exists
    doc_id = str(uuid.uuid4())
    image_out_dir = os.path.join(image_dir, doc_id)
    ensure_directory_exists(image_out_dir)  

    # Open the PDF file and iterate pages
    print('Extracting images from PDF...')
    pdf_document = fitz.open(pdf_path)  

    for page_number in range(len(pdf_document)):  
        page = pdf_document.load_page(page_number)  
        image = page.get_pixmap()  
        image_out_file = os.path.join(image_out_dir, f'{page_number + 1}.png')
        image.save(image_out_file)  
        if page_number % 100 == 0:
            print(f'Processed {page_number} images...')  

    pdf_document.close()
    return doc_id

# Base64 encode images
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")
        
# Find all files in a dir
def get_all_files(directory_path):  
    files = []  
    for entry in os.listdir(directory_path):  
        entry_path = os.path.join(directory_path, entry)  
        if os.path.isfile(entry_path):  
            files.append(entry_path)  
    return files  
  
@retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
def extract_markdown_from_image(image_path):
    try:
        base64_image = encode_image(image_path)
        client = _get_gpt_client()
        response = client.chat.completions.create(
            model=_get_gpt_deployment_name(),
            messages=[
                { "role": "system", "content": "You are a helpful assistant." },
                { "role": "user", "content": [  
                    { 
                        "type": "text", 
                        "text": """Extract everything you see in this image to markdown. 
                            Convert all charts such as line, pie and bar charts to markdown tables and include a note that the numbers are approximate.
                        """ 
                    },
                    {
                        "type": "image_url", 
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                    }
                ] } 
            ],
            max_tokens=2000 
        )
        print(response.choices[0].message.content)
        return response.choices[0].message.content
    except Exception as ex:
        print(f"Error extracting markdown from image: {ex}")
        return ""

def process_image(file, markdown_out_dir):
    if '.png' in file:
        print('Processing:', file)
        markdown_file_out = os.path.join(markdown_out_dir, os.path.basename(file).replace('.png', '.txt'))
        print(markdown_file_out)
        if os.path.exists(markdown_file_out) == False:
            markdown_text = extract_markdown_from_image(file)
            with open(markdown_file_out, 'w', encoding='utf-8') as md_out:
                md_out.write(markdown_text)
        else:
            print('Skipping processed file.')
    else:
        print('Skipping non PNG file:', file)

    return file

def process_document_to_markdown(document_path, output_dir=None):
    """
    Main function to process a document and return markdown content.
    This is a simplified version that uses the existing functions.
    """
    try:
        # Convert document to PDF first
        pdf_path = convert_to_pdf(document_path)
        if not pdf_path:
            return f"# Error Processing Document\n\nCould not convert {os.path.basename(document_path)} to PDF"
        
        # Extract PDF pages to images
        ensure_directory_exists('images')
        doc_id = extract_pdf_pages_to_images(pdf_path, 'images')
        
        # Process images to extract markdown
        pdf_images_dir = os.path.join('images', doc_id)
        files = get_all_files(pdf_images_dir)
        
        ensure_directory_exists('markdown')
        markdown_out_dir = os.path.join('markdown', doc_id)
        ensure_directory_exists(markdown_out_dir)
        
        # Process all images
        markdown_content = f"# {os.path.basename(document_path)}\n\n"
        
        # Sort files by page number
        files.sort(key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
        
        for file in files:
            if '.png' in file:
                page_num = os.path.splitext(os.path.basename(file))[0]
                markdown_text = extract_markdown_from_image(file)
                if markdown_text:
                    markdown_content += f"## Page {page_num}\n\n{markdown_text}\n\n"
        
        return markdown_content
        
    except Exception as e:
        print(f"Error processing document {document_path}: {e}")
        return f"# Error Processing Document\n\nFile: {os.path.basename(document_path)}\nError: {str(e)}"
