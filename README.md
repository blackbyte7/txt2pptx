# txt2pptx: Text-to-PowerPoint Presentation Generator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Langchain](https://img.shields.io/badge/Langchain-latest-orange.svg)](https://python.langchain.com)

## Overview

`txt2pptx` is a Python-based project leveraging the power of Langchain and Large Language Models (LLMs) to automatically generate PowerPoint presentations from user-provided text or PDF content.  Simply input your text, choose a presentation style, and `txt2pptx` will create a professional-looking presentation for you, complete with structured slides, bullet points, and style customizations.

This project aims to streamline the presentation creation process, saving you time and effort by automating the conversion of textual information into visually engaging slides. It's ideal for quickly generating presentations for meetings, lectures, reports, and more.

## Features

- **Text and PDF Input:** Accepts both plain text and PDF files as input for generating presentations.
- **Style Customization:** Offers various presentation styles (e.g., Professional, Creative) to tailor the look and feel of your slides.
- **LLM Powered Generation:** Utilizes Langchain and LLMs (OpenAI or Anthropic) to intelligently structure content into logical slides and bullet points.
- **Automated Presentation Creation:** Generates `.pptx` files programmatically using the `python-pptx` library.
- **Documentation Retrieval (RAG):**  Leverages Retrieval-Augmented Generation (RAG) using `python-pptx` documentation to generate accurate and relevant PowerPoint code.
- **Content Analysis:** Provides optional content analysis and suggestions to improve the clarity and impact of your presentation.
- **Export Options:** Supports exporting presentations to various formats including PDF, HTML, and individual image slides.
- **Template Customization:** Allows for customization of presentation templates, including colors, fonts, and transitions.
- **Gradio User Interface:**  Includes a user-friendly Gradio web interface for easy interaction and presentation generation.
- **Logging:** Integrated logging for monitoring application behavior and debugging.

## Installation

1. **Clone the repository:**

   ```bash
   git clone <repository_url>
   cd txt2pptx
   ```

2. **Set up a virtual environment (recommended):**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Linux/macOS
   venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables:**

   - Create a `.env` file in the project root directory.
   - Add your OpenAI or Anthropic API key to the `.env` file:

     ```env
     OPENAI_API_KEY='your_secret_key'
     # Or for Anthropic
     # ANTHROPIC_API_KEY='your_anthropic_api_key'
     ```
     **Note:** If you plan to use Anthropic, ensure you select "Anthropic" in the Gradio UI and have the necessary API key configured.

5. **Install system-level dependencies (for PDF and advanced export features):**

   - **For PDF conversion on Unix-based systems (Linux, macOS):**
     ```bash
     sudo apt-get install unoconv libreoffice  # Debian/Ubuntu based
     # or
     brew install unoconv libreoffice         # macOS using Homebrew
     # or use your system's package manager
     ```
     Ensure `unoconv` and `libreoffice` are installed and accessible in your system's PATH.
   - **For PDF to image conversion:**
     Install `poppler` (required by `pdf2image`). Instructions vary by OS; for Ubuntu:
     ```bash
     sudo apt-get install poppler-utils
     ```
     Refer to the `pdf2image` documentation for installation instructions on other operating systems.

## Usage

1. **Run the Gradio UI:**

   ```bash
   python run.py
   ```

2. **Access the UI in your browser:**

   Open your web browser and go to the address displayed in the console (usually `http://127.0.0.1:7860`).

3. **Using the Web Interface:**

   - **Input File:** Upload a `.txt` or `.pdf` file containing the content for your presentation.
   - **Presentation Style:** Choose a style from the dropdown menu (Default, Professional, Creative, Playful).
   - **LLM Provider:** Select your preferred LLM provider (OpenAI or Anthropic).
   - **API Key:** Enter your API key if you don't want to use the environment variable or want to use a different key.
   - **Presentation Template:** Choose a base template to start with (professional, creative).
   - **Advanced Options (Tab):**
     - **Export Formats:** Select the formats you want to export your presentation to (PDF, HTML, Images).
     - **Analyze Content:** Check this box to enable content analysis and get suggestions for improvement.
     - **Template Customization:**  Optionally customize the presentation template by providing a JSON object with modifications to colors, fonts, and transitions.
   - **Generate Presentation:** Click the "Generate Presentation" button to start the presentation creation process.

4. **Download Generated Presentation(s):**

   Once the process is complete, the generated `.pptx` file (and any exported files) will be available for download in the "Generated Presentation(s)" section of the UI.

## Directory Structure

```
txt2pptx/
├── app/
│   ├── agents.py         # Defines the presentation agent and orchestration logic.
│   ├── analyzers.py      # Implements content analysis for presentation improvement.
│   ├── exporters.py      # Handles exporting presentations to different formats (PDF, HTML, images).
│   ├── rag.py            # Implements Retrieval-Augmented Generation for documentation lookup.
│   ├── tools.py          # Defines custom Langchain tools for presentation generation tasks.
│   ├── utils.py          # Utility functions for file loading, presentation generation, etc.
├── environment.env       # Environment variable configuration file.
├── log_config/
│   └── logging_config.py # Logging setup and configuration.
├── requirements.txt      # Project dependencies.
├── run.py              # Main script to launch the Gradio UI.
├── templates/
│   ├── templates.py      # Manages presentation templates and customization.
│   └── professional.json  # Example template definition (you might have more).
├── view/
│   └── gradio_ui.py     # Gradio user interface definition.
└── README.md             # Project README file (this document).
```

## Environment Variables

- `OPENAI_API_KEY`: Your OpenAI API key. Required if using OpenAI models.
- `ANTHROPIC_API_KEY`: Your Anthropic API key. Required if using Anthropic models.

   **Note:** It is highly recommended to use environment variables to securely manage your API keys instead of hardcoding them in the code.

## Dependencies

- `langchain>=0.2.17`
- `langchain-community`
- `langchain-openai`
- `langchain-anthropic`
- `gradio~=5.11.0`
- `pdf2image==1.16.3`
- `python-pptx==0.6.21`
- `pydantic>=2.10.0`
- `comtypes>=1.1.14; platform_system == "Windows"`
- `pywin32>=305; platform_system == "Windows"`
- `unoconv` (for Unix-based PDF conversion)
- `python-dotenv~=1.0.1`
- `langgraph~=0.3.15`
- `pypdf`

   See `requirements.txt` for the full list of dependencies and specific versions.

## Contributing

Contributions to `txt2pptx` are welcome! If you have ideas for improvements, new features, or bug fixes, please feel free to:

1. Fork the repository.
2. Create a new branch for your feature or fix.
3. Make your changes and commit them.
4. Submit a pull request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

- Built using [Langchain](https://python.langchain.com/) - for powerful language model orchestration.
- Utilizes [OpenAI](https://openai.com/) and [Anthropic](https://www.anthropic.com/) models - for natural language processing and content generation.
- PowerPoint generation powered by [python-pptx](https://python-pptx.readthedocs.io/en/latest/) - for programmatic PowerPoint manipulation.
- Gradio UI created with [Gradio](https://gradio.app/) - for user-friendly web interface.
- PDF handling with [pdf2image](https://github.com/Belval/pdf2image) and system tools.

---

**Note:** This project utilizes external LLM APIs (OpenAI/Anthropic). API key configuration and responsible usage are required.
