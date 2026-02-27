# Questions-Done-Quick

## Snippet hotkeys

- Press the **Left Arrow** to define the **top-left** corner of the snippet.
- Press the **Right Arrow** to define the **bottom-right** corner of the snippet.
- The model response will appear in the **Windows system tray**.

## Environment variables

Create or edit `.env` in the project root with up to four Gemini API keys:

```envp
GEMINI_API_KEY=
GEMINI_API_KEY_SECOND=
GEMINI_API_KEY_THIRD=
GEMINI_API_KEY_FOURTH=
```

## Portable Python virtual environment (Windows)

1. Ensure Python 3.11+ is installed.
2. Create a local virtual environment in this folder:

   ```powershell
   py -3.11 -m venv .venv
   ```

3. Activate it:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

4. Install dependencies:

   ```powershell
   pip install -e .
   ```

5. Run the app:

   ```powershell
   .\run_main.bat
   ```
