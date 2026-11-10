"""Errors whose message was written for the person and may be returned to them."""


class PublicMessageError(Exception):
    """An error raised with a message that is safe to show.

    Raise it only with text Floppy wrote. Never wrap ``str(other_exception)``:
    a view returns ``message`` without looking at it again.
    """

    def __init__(self, message="", *args):
        """Keep the message on its own attribute."""
        super().__init__(message, *args)
        self.message = str(message)
