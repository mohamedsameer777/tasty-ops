from whitenoise.storage import CompressedManifestStaticFilesStorage


class LenientManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    Same as WhiteNoise's normal storage, but doesn't fail the whole deploy
    if a CSS file references another file that's missing (e.g. Django
    REST Framework's bootstrap.min.css pointing at a .map file it doesn't
    actually ship, or the admin's base.css referencing an icon that isn't
    present in this Django version). Those references are just left as-is
    instead of being hashed — completely harmless, since nothing in this
    app actually needs those specific files to load.
    """
    manifest_strict = False