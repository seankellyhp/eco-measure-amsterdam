# Jupyter settings for this workshop, read when Jupyter is started from this folder.
c = get_config()  # noqa: F821

# No token or password: the server only listens on this computer (localhost).
c.IdentityProvider.token = ""

# Open the tutorial notebook straight away.
c.LabApp.default_url = "/lab/tree/notebooks/getting-started.ipynb"
