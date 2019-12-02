import subprocess


def safe_check_call(self, command: str, error_message: str) -> None:
    """
    Safely wrap subprocess.check_output to ensure we always return 0 and
    log the error messages
    """
    try:
        subprocess.check_call(command)
    except subprocess.CalledProcessError as ex:
        self.exit_gracefully(msg=error_message, e=ex.output)


def popup_message(self, msg: str) -> None:
    safe_check_call(
        command=[
            "notify-send",
            "--expire-time",
            "3000",
            "--icon",
            "/usr/share/securedrop/icons/sd-logo.png",
            "SecureDrop: {}".format(msg),
        ],
        error_message="Error sending notification:"
    )
