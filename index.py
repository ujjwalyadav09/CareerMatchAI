"""Vercel entrypoint: Vercel's Flask runtime serves the `app` object defined here."""
from careermatch.app import create_app

app = create_app()
