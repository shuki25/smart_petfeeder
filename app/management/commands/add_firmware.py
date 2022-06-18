import os
import shutil
from io import BytesIO

from django.core.management.base import BaseCommand

from smart_petfeeder.settings import FIRMWARE_INSTALL_PATH, FIRMWARE_BUILD_PATH
from app.models import ControlBoardModel, FirmwareUpdate


class Command(BaseCommand):
    help = "Install new firmware to firmware repository"
    builds = ["esp32-revC-1g", "esp32-revC-2g", "esp32-s2-revD-1g"]

    def add_arguments(self, parser):
        parser.add_argument("-f", "--force", action='store_true', help="Force install")

    def handle(self, *args, **options):
        for build in self.builds:
            self.stdout.write(f"Installing {build}")
            firmware_file = os.path.join(FIRMWARE_BUILD_PATH, build, "firmware.bin")
            self.stdout.write(f"Firmware file: {firmware_file}")
            # Open the firmware file to get version
            try:
                with open(firmware_file, "rb") as f:
                    f.seek(0x30, 0)
                    bin_str = f.read(16)
                    firmware_version = BytesIO(bin_str).getvalue().rstrip(b"\x00").decode()
                    self.stdout.write("New Firmware version: %s" % firmware_version)
                    f.seek(0x63, 0)
                    bin_str = f.read(13)
                    control_board_version = BytesIO(bin_str).getvalue().rstrip(b"\x00").decode()

                    self.stdout.write("New Control board version: %s" % control_board_version)
                    firmware_install_file = os.path.join(
                        FIRMWARE_INSTALL_PATH, "firmware-rev%s-current.bin" % control_board_version
                    )
            except FileNotFoundError:
                self.stdout.write("Firmware file not found")
                continue

            try:
                control_board_model = ControlBoardModel.objects.get(revision=control_board_version)
            except ControlBoardModel.DoesNotExist:
                self.stdout.write("Control board is not listed as supported board, not installing")
                continue

            # Open the firmware install destination file to get version
            self.stdout.write("Current Firmware install file: %s" % firmware_install_file)
            try:
                with open(firmware_install_file, "rb") as f:
                    f.seek(0x30, 0)
                    bin_str = f.read(16)
                    firmware_install_version = BytesIO(bin_str).getvalue().rstrip(b"\x00").decode()
                    self.stdout.write("Old Firmware install version: %s" % firmware_install_version)
                    f.seek(0x63, 0)
                    bin_str = f.read(13)
                    control_board_install_version = BytesIO(bin_str).getvalue().rstrip(b"\x00").decode()
                    self.stdout.write("Old Control board install version: %s" % control_board_install_version)
                    backup_firmware_install_file = os.path.join(
                        FIRMWARE_INSTALL_PATH, "firmware-rev%s-%s.bin" % (control_board_version, firmware_install_version)
                    )
            except FileNotFoundError:
                self.stdout.write("No old firmware install file found")
                self.stdout.write("Installing new firmware")
                shutil.copy(firmware_file, firmware_install_file)
                self.stdout.write("New firmware installed")
                FirmwareUpdate.objects.create(
                    version=firmware_version,
                    description="* Fixed bug with firmware update",
                    control_board=control_board_model,
                )
                continue

            if firmware_version == firmware_install_version and control_board_version == control_board_install_version:
                self.stdout.write("Firmware version is the same, not installing")
                continue
            elif control_board_version != control_board_install_version and not options["force"]:
                self.stdout.write("Control board version is different, not installing")
                continue
            else:
                self.stdout.write("Firmware version is different, installing")
                self.stdout.write("Backing up old firmware install to: %s" % backup_firmware_install_file)
                os.rename(firmware_install_file, backup_firmware_install_file)
                self.stdout.write("Installing new firmware")
                shutil.copy(firmware_file, firmware_install_file)
                self.stdout.write("New firmware installed")

                FirmwareUpdate.objects.create(
                    version=firmware_version,
                    description="* Fixed bug with firmware update",
                    control_board=control_board_model,
                )
