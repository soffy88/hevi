"""Runtime configuration failures that true process entrypoints must handle."""


class ConfigurationError(RuntimeError):
    """Invalid runtime configuration (missing/weak secrets, bad env).

    Raised by the config layer. Entrypoints decide whether to exit.
    """
