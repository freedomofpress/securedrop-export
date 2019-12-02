import logging
import signal
import subprocess
import time
import os

from securedrop_export.exceptions import ExportStatus, TimeoutException, handler
from securedrop_export.export import ExportAction
from securedrop_export.utils import safe_check_call


PRINTER_NAME = "sdw-printer"
PRINTER_WAIT_TIMEOUT = 60
BRLASER_DRIVER = "/usr/share/cups/drv/brlaser.drv"
BRLASER_PPD = "/usr/share/cups/model/br7030.ppd"

logger = logging.getLogger(__name__)


class PrintActionMixin(object):
    """
    All print-related actions inherit from this class.
    """
    def __init__(self):
        self.printer_name = PRINTER_NAME
        self.printer_wait_timeout = PRINTER_WAIT_TIMEOUT
        self.brlaser_driver = BRLASER_DRIVER
        self.brlaser_ppd = BRLASER_PPD

    def print_file(self, file_to_print: str):
        # If the file to print is an (open)office document, we need to call unoconf to
        # convert the file to pdf as printer drivers do not support this format
        if self.is_open_office_file(file_to_print):
            logging.info('Converting Office document to pdf'.format(self.printer_name))
            folder = os.path.dirname(file_to_print)
            converted_filename = file_to_print + ".pdf"
            converted_path = os.path.join(folder, converted_filename)
            safe_check_call(
                command=["unoconv", "-o", converted_path, file_to_print],
                error_message=ExportStatus.ERROR_PRINT.value
            )
            file_to_print = converted_path

        logging.info('Sending file to printer {}:{}'.format(self.printer_name))
        safe_check_call(
            command=["xpp", "-P", self.printer_name, file_to_print],
            error_message=ExportStatus.ERROR_PRINT.value
        )

    def install_printer_ppd(self, uri):
        # Some drivers don't come with ppd files pre-compiled, we must compile them
        if "Brother" in uri:
            safe_check_call(
                command=[
                    "sudo",
                    "ppdc",
                    self.brlaser_driver,
                    "-d",
                    "/usr/share/cups/model/",
                ],
                error_message=ExportStatus.ERROR_PRINTER_DRIVER_UNAVAILABLE.value
            )
            return self.brlaser_ppd
        # Here, we could support ppd drivers for other makes or models in the future

    def setup_printer(self, printer_uri, printer_ppd):
        # Add the printer using lpadmin
        safe_check_call(
            command=[
                "sudo",
                "lpadmin",
                "-p",
                self.printer_name,
                "-v",
                printer_uri,
                "-P",
                printer_ppd,
            ],
            error_message=ExportStatus.ERROR_PRINTER_INSTALL.value
        )
        # Activate the printer so that it can receive jobs
        safe_check_call(
            command=["sudo", "lpadmin", "-p", self.printer_name, "-E"],
            error_message=ExportStatus.ERROR_PRINTER_INSTALL.value
        )
        # Allow user to print (without using sudo)
        safe_check_call(
            command=["sudo", "lpadmin", "-p", self.printer_name, "-u", "allow:user"],
            error_message=ExportStatus.ERROR_PRINTER_INSTALL.value
        )

    def print_test_page(self):
        self.print_file("/usr/share/cups/data/testprint")
        self.popup_message("Printing test page")

    def print_all_files(self, tmpdir: str):
        files_path = os.path.join(tmpdir, "export_data/")
        files = os.listdir(files_path)
        print_count = 0
        for f in files:
            file_path = os.path.join(files_path, f)
            self.print_file(file_path)
            print_count += 1
            msg = "Printing document {} of {}".format(print_count, len(files))
            self.popup_message(msg)

    def is_open_office_file(self, filename):
        OPEN_OFFICE_FORMATS = [
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".odt",
            ".ods",
            ".odp",
        ]
        for extension in OPEN_OFFICE_FORMATS:
            if os.path.basename(filename).endswith(extension):
                return True
        return False

    def wait_for_print(self):
        # use lpstat to ensure the job was fully transfered to the printer
        # returns True if print was successful, otherwise will throw exceptions
        signal.signal(signal.SIGALRM, handler)
        signal.alarm(self.printer_wait_timeout)
        printer_idle_string = "printer {} is idle".format(self.printer_name)
        while True:
            try:
                logging.info('Running lpstat waiting for printer {}'.format(self.printer_name))
                output = subprocess.check_output(["lpstat", "-p", self.printer_name])
                if printer_idle_string in output.decode("utf-8"):
                    logging.info('Print completed')
                    return True
                else:
                    time.sleep(5)
            except subprocess.CalledProcessError:
                self.exit_gracefully(ExportStatus.ERROR_PRINT.value)
            except TimeoutException:
                logging.error('Timeout waiting for printer {}'.format(self.printer_name))
                self.exit_gracefully(ExportStatus.ERROR_PRINT.value)
        return True

    def get_printer_uri(self):
        # Get the URI via lpinfo and only accept URIs of supported printers
        printer_uri = ""
        try:
            output = subprocess.check_output(["sudo", "lpinfo", "-v"])
        except subprocess.CalledProcessError:
            self.exit_gracefully(ExportStatus.ERROR_PRINTER_URI.value)

        # fetch the usb printer uri
        for line in output.split():
            if "usb://" in line.decode("utf-8"):
                printer_uri = line.decode("utf-8")
                logging.info('lpinfo usb printer: {}'.format(printer_uri))

        # verify that the printer is supported, else exit
        if printer_uri == "":
            # No usb printer is connected
            logging.info('No usb printers connected')
            self.exit_gracefully(ExportStatus.ERROR_PRINTER_NOT_FOUND.value)
        elif "Brother" in printer_uri:
            logging.info('Printer {} is supported'.format(printer_uri))
            return printer_uri
        else:
            # printer url is a make that is unsupported
            logging.info('Printer {} is unsupported'.format(printer_uri))
            self.exit_gracefully(ExportStatus.ERROR_PRINTER_NOT_SUPPORTED.value)


class PrintExportAction(ExportAction, PrintActionMixin):
    def __init__(self, submission):
        self.submission = submission

    def run(self):
        logging.info('Export archive is printer')
        # prints all documents in the archive
        logging.info('Searching for printer')
        printer_uri = self.get_printer_uri()
        logging.info('Installing printer drivers')
        printer_ppd = self.install_printer_ppd(printer_uri)
        logging.info('Setting up printer')
        self.setup_printer(printer_uri, printer_ppd)
        logging.info('Printing files')
        self.print_all_files(self.submission.tmpdir)


class PrintTestPageAction(ExportAction, PrintActionMixin):
    def __init__(self, submission):
        # OBSERVATION: We're not actually using submission anywhere here
        self.submission = submission

    def run(self):
        # Prints a test page to ensure the printer is functional
        printer_uri = self.get_printer_uri()
        printer_ppd = self.install_printer_ppd(printer_uri)
        self.setup_printer(printer_uri, printer_ppd)
        self.print_test_page()
