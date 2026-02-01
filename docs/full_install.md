# Full Installation Guide

## Prerequisites

- **OS**: Windows (tested), Linux/Mac (compatible)
- **Python**: 3.10+
- **Git**: Just for cloning
- **GPU**: NVIDIA GPU recommended for local LLMs (Torch/CUDA).

## Step-by-Step

1. **Clone the Repository**

    ```bash
    git clone https://github.com/your-repo/genesis.git
    cd genesis
    ```

2. **Set up Virtual Environment**
    It is highly recommended to use a virtual environment.

    ```bash
    python -m venv env
    .\env\Scripts\activate   # Windows
    # source env/bin/activate # Linux/Mac
    ```

3. **Install Dependencies**

    ```bash
    pip install -r requirements.txt
    ```

    *Note: If you have issues with Torch/BitandBytes, ensure you have the correct CUDA version installed.*

4. **Configure Environment**
    Create a `.env` file (optional) or set environment variables:
    - `GENESIS_HOME`: Path to base directory.
    - `SECRET_KEY`: Flask secret key.

5. **Run the Server**

    ```bash
    .\run.bat gui
    ```

    Or manually:

    ```bash
    python app.py
    ```

6. **Access the UI**
    Open your browser and navigate to: `http://127.0.0.1:5000`

## Troubleshooting

- **"Module not found"**: Ensure your virtual environment is activated.
- **"Torch/CUDA errors"**: reinstall torch with the correct CUDA version from [pytorch.org](https://pytorch.org).
