import logging

from securedrop_export import export
from securedrop_export.export import ExportStatus

logger = logging.getLogger(__name__)


def __main__(submission):
    submission.extract_tarball()

    try:
        submission.archive_metadata = export.Metadata(submission.tmpdir)
    except Exception:
        submission.exit_gracefully(ExportStatus.ERROR_METADATA_PARSING.value)

    if submission.archive_metadata.is_valid():
        logging.info('Export archive is {}'.format(submission.archive_metadata.export_method))
        if submission.archive_metadata.export_method == "disk-check":
            submission.check_luks_volume()
        elif submission.archive_metadata.export_method == "disk":
            # exports all documents in the archive to luks-encrypted volume
            submission.unlock_luks_volume(submission.archive_metadata.encryption_key)
            submission.mount_volume()
            submission.copy_submission()
        elif submission.archive_metadata.export_method == "printer-check":
            submission.check_printer_connected()
        elif submission.archive_metadata.export_method == "printer":
            # prints all documents in the archive
            submission.setup_printer()
            submission.print_all_files()
        elif submission.archive_metadata.export_method == "printer-test":
            # Prints a test page to ensure the printer is functional
            submission.setup_printer()
            submission.print_test_page()
    else:
        submission.exit_gracefully(ExportStatus.ERROR_ARCHIVE_METADATA.value)
