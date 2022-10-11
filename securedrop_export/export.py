#!/usr/bin/env python3

import abc
import datetime
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile

from securedrop_export.exceptions import ExportStatus
from securedrop_export.utils import safe_extractall

logger = logging.getLogger(__name__)


class Metadata(object):
    """
    Object to parse, validate and store json metadata from the sd-export archive.
    """

    METADATA_FILE = "metadata.json"
    SUPPORTED_EXPORT_METHODS = [
        "start-vm",
        "usb-test",  # general preflight check
        "disk",
        "disk-test",  # disk preflight test
        "printer",
        "printer-test",  # print test page
        "printer-preflight",
    ]
    SUPPORTED_ENCRYPTION_METHODS = ["luks"]

    def __init__(self, archive_path):
        self.metadata_path = os.path.join(archive_path, self.METADATA_FILE)

        try:
            with open(self.metadata_path) as f:
                logger.info("Parsing archive metadata")
                json_config = json.loads(f.read())
                self.export_method = json_config.get("device", None)
                self.encryption_method = json_config.get("encryption_method", None)
                self.encryption_key = json_config.get("encryption_key", None)
                logger.info(
                    "Exporting to device {} with encryption_method {}".format(
                        self.export_method, self.encryption_method
                    )
                )

        except Exception:
            logger.error("Metadata parsing failure")
            raise

    def is_valid(self):
        logger.info("Validating metadata contents")
        if self.export_method not in self.SUPPORTED_EXPORT_METHODS:
            logger.error(
                "Archive metadata: Export method {} is not supported".format(
                    self.export_method
                )
            )
            return False

        if self.export_method == "disk":
            if self.encryption_method not in self.SUPPORTED_ENCRYPTION_METHODS:
                logger.error(
                    "Archive metadata: Encryption method {} is not supported".format(
                        self.encryption_method
                    )
                )
                return False
        return True


class SDExport(object):
    def __init__(self, archive, config_path):
        os.umask(0o022)
        self.archive = archive
        self.submission_dirname = os.path.basename(self.archive).split(".")[0]
        self.target_dirname = "sd-export-{}".format(
            datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        )
        self.tmpdir = tempfile.mkdtemp()

    def extract_tarball(self):
        try:
            logger.info(
                "Extracting tarball {} into {}".format(self.archive, self.tmpdir)
            )
            safe_extractall(self.archive, self.tmpdir)
        except Exception as ex:
            logger.error("Unable to extract tarball: {}".format(ex))
            self.exit_gracefully(ExportStatus.ERROR_EXTRACTION.value)

    def exit_gracefully(self, msg, e=False):
        """
        Utility to print error messages, mostly used during debugging,
        then exits successfully despite the error. Always exits 0,
        since non-zero exit values will cause system to try alternative
        solutions for mimetype handling, which we want to avoid.
        """
        logger.info("Exiting with message: {}".format(msg))
        if e:
            logger.error("Captured exception output: {}".format(e.output))
        try:
            # If the file archive was extracted, delete before returning
            if os.path.isdir(self.tmpdir):
                shutil.rmtree(self.tmpdir)
            # Do this after deletion to avoid giving the client two error messages in case of the
            # block above failing
            sys.stderr.write(msg)
            sys.stderr.write("\n")
        except Exception as ex:
            logger.error("Unhandled exception: {}".format(ex))
            sys.stderr.write(ExportStatus.ERROR_GENERIC.value)
        # exit with 0 return code otherwise the os will attempt to open
        # the file with another application
        sys.exit(0)

    def safe_check_call(self, command, error_message, ignore_stderr_startswith=None):
        """
        Safely wrap subprocess.check_output to ensure we always return 0 and
        log the error messages
        """
        try:
            err = subprocess.run(command, check=True, capture_output=True).stderr
            # ppdc and lpadmin may emit warnings we are aware of which should not be treated as
            # user facing errors
            if ignore_stderr_startswith and err.startswith(ignore_stderr_startswith):
                logger.info("Encountered warning: {}".format(err.decode("utf-8")))
            elif err == b"":
                # Nothing on stderr and returncode is 0, we're good
                pass
            else:
                self.exit_gracefully(msg=error_message, e=err)
        except subprocess.CalledProcessError as ex:
            self.exit_gracefully(msg=error_message, e=ex.output)


class ExportAction(abc.ABC):
    """
    This export interface defines the method that export
    methods should implement.
    """

    @abc.abstractmethod
    def run(self) -> None:
        """Run logic"""
        pass
