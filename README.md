# CinemaBackOffice
# import from sumup and create backoffice.

# Cinema Affiche Generator

## Install
python -m venv .venv
source .venv/bin/activate  # mac/linux
# .venv\Scripts\activate   # windows

pip install -r requirements.txt

## Extra (voor MVG / "fake PNG" icons)
- macOS: brew install imagemagick
- Windows: install ImageMagick, ensure `magick` is on PATH

## Run
python app.py

## Notes
- Put "goedgezien" icons into ./icons (png/jpg/jpeg/svg/mvg...).
- If Pillow can't open an icon, the app will rasterize it via ImageMagick.