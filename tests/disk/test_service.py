import pytest
from unittest import mock

import os
import pytest
import sys
import tempfile

import subprocess
from subprocess import CalledProcessError

from securedrop_export.enums import ExportEnum
from securedrop_export.exceptions import ExportException
from securedrop_export.disk.status import Status
from securedrop_export.disk.new_status import Status as NewStatus
from securedrop_export.disk.volume import Volume, EncryptionScheme

from securedrop_export.archive import Archive, Metadata
from securedrop_export.disk.service import Service
from securedrop_export.disk.cli import CLI

TEST_CONFIG = os.path.join(os.path.dirname(__file__), "sd-export-config.json")
SAMPLE_OUTPUT_LSBLK_NO_PART = b"disk\ncrypt"  # noqa
SAMPLE_OUTPUT_USB = "/dev/sda"  # noqa
SAMPLE_OUTPUT_USB_PARTITIONED = "/dev/sda1"

class TestExportService:

    @classmethod
    def setup_class(cls):
        cls.mock_cli = mock.MagicMock(CLI)
        cls.mock_submission = cls._setup_submission()

        cls.mock_luks_volume_unmounted = Volume(device_name=SAMPLE_OUTPUT_USB, mapped_name="fake-luks-id-123456", encryption=EncryptionScheme.LUKS)
        cls.mock_luks_volume_mounted = Volume(device_name=SAMPLE_OUTPUT_USB, mapped_name="fake-luks-id-123456", mountpoint="/media/usb", encryption=EncryptionScheme.LUKS)

        cls.service = Service(cls.mock_submission, cls.mock_cli)

    @classmethod
    def teardown_class(cls):
        cls.mock_cli = None
        cls.mock_submission = None
        cls.service = None

    @classmethod
    def _setup_submission(cls) -> Archive:
        """
        Helper method to set up sample archive
        """
        submission = Archive("testfile", TEST_CONFIG)
        temp_folder = tempfile.mkdtemp()
        metadata = os.path.join(temp_folder, Metadata.METADATA_FILE)
        with open(metadata, "w") as f:
            f.write('{"device": "disk", "encryption_method": "luks", "encryption_key": "hunter1"}')

        submission.archive_metadata = Metadata.create_and_validate(temp_folder)

        return submission

    def setup_method(self, method):
        """
        By default, mock CLI will return the "happy path" of a correctly-formatted LUKS drive.
        Override this behaviour in the target method as required, for example to simulate CLI
        errors. `teardown_method()` will reset the side effects so they do not affect subsequent
        test methods.
        """
        self.mock_cli.get_connected_devices.return_value = [SAMPLE_OUTPUT_USB]
        self.mock_cli.get_partitioned_device.return_value = SAMPLE_OUTPUT_USB_PARTITIONED
        self.mock_cli.get_luks_volume.return_value = self.mock_luks_volume_unmounted
        self.mock_cli.mount_volume.return_value = self.mock_luks_volume_mounted

    def teardown_method(self, method):
        self.mock_cli.reset_mock(return_value=True, side_effect=True)

    def test_check_usb(self):
        status = self.service.check_connected_devices()

        assert status is Status.LEGACY_USB_CONNECTED

    def test_check_usb_error_no_devices(self):
        self.mock_cli.get_connected_devices.side_effect = ExportException(sdstatus=NewStatus.NO_DEVICE_DETECTED)

        with pytest.raises(ExportException) as ex:
            self.service.check_connected_devices()

        assert ex.value.sdstatus is Status.LEGACY_ERROR_GENERIC

    def test_check_usb_error_multiple_devices(self):
        self.mock_cli.get_connected_devices.side_effect = ExportException(sdstatus=NewStatus.MULTI_DEVICE_DETECTED)

        with pytest.raises(ExportException) as ex:
            self.service.check_connected_devices()

        assert ex.value.sdstatus is Status.LEGACY_ERROR_GENERIC

    def test_check_usb_error_while_checking(self):
        self.mock_cli.get_connected_devices.side_effect = ExportException(sdstatus=Status.LEGACY_ERROR_USB_CHECK)

        with pytest.raises(ExportException) as ex:
            self.service.check_connected_devices()

        assert ex.value.sdstatus is Status.LEGACY_ERROR_GENERIC

    def test_check_disk_format(self):
        status = self.service.check_disk_format()

        assert status is Status.LEGACY_USB_ENCRYPTED

    def test_check_disk_format_error(self):
        self.mock_cli.get_partitioned_device.side_effect=ExportException(sdstatus=NewStatus.INVALID_DEVICE_DETECTED)

        with pytest.raises(ExportException) as ex:
            self.service.check_disk_format()

        # We still return the legacy status for now 
        assert ex.value.sdstatus is Status.LEGACY_USB_ENCRYPTION_NOT_SUPPORTED

    def test_export(self):
        status = self.service.export()
        assert status is Status.SUCCESS_EXPORT

    def test_export_disk_not_supported(self):
        self.mock_cli.is_luks_volume.return_value = False

        with pytest.raises(ExportException) as ex:
            self.service.export()

        assert ex.value.sdstatus is Status.LEGACY_USB_ENCRYPTION_NOT_SUPPORTED

    def test_export_write_error(self):
        self.mock_cli.is_luks_volume.return_value=True
        self.mock_cli.write_data_to_device.side_effect = ExportException(sdstatus=Status.LEGACY_ERROR_USB_WRITE)

        with pytest.raises(ExportException) as ex:
            self.service.export()

        assert ex.value.sdstatus is Status.LEGACY_ERROR_USB_WRITE