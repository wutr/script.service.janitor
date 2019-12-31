#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
import re
import time
from ctypes import *

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from settings import *

# Addon info
ADDON_ID = "script.service.janitor"
ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name")
ADDON_PROFILE = xbmc.translatePath(ADDON.getAddonInfo("profile"))
ADDON_ICON = xbmc.translatePath(ADDON.getAddonInfo("icon"))


class Log(object):
    """
    The Log class will handle the writing of cleaned files to a log file in the addon settings.

    This log file will be automatically created upon first prepending data to it.

    Supported operations are prepend, trim, clear and get.
    """
    def __init__(self):
        self.logpath = os.path.join(ADDON_PROFILE, "cleaner.log")

    def prepend(self, data):
        """
        Prepend the given data to the current log file. Will create a new log file if none exists.

        :type data: list
        :param data: A list of strings to prepend to the log file.
        """
        try:
            debug("Prepending the log file with new data.")
            debug("Backing up current log.")
            with open(self.logpath, "a+") as f:  # use append mode to make sure it is created if non-existent
                previous_data = f.read()
        except (IOError, OSError) as err:
            debug("{0}".format(err, xbmc.LOGERROR))
        else:
            try:
                debug("Writing new log data.")
                with open(self.logpath, "w") as f:
                    if data:
                        f.write("[B][{time}][/B]\n".format(time=time.strftime("%d/%m/%Y  -  %H:%M:%S")))
                        for line in data:
                            line = line.encode("utf-8")
                            f.write(" - {0}\n".format(line))
                        f.write("\n")
                        debug("New data written to log file.")
                    else:
                        debug("No data to write. Stopping.")

                    debug("Appending previous log file contents.")
                    f.writelines(previous_data.encode("utf-8"))
            except (IOError, OSError) as err:
                debug("{0}".format(err), xbmc.LOGERROR)

    def trim(self, lines_to_keep=25):
        """
        Trim the log file to contain a maximum number of lines.

        :type lines_to_keep: int
        :param lines_to_keep: The number of lines to preserve. Any lines beyond this number get erased. Defaults to 25.
        :rtype: unicode
        :return: The contents of the log file after trimming.
        """
        try:
            debug("Trimming log file contents.")
            with open(self.logpath) as f:
                debug("Saving the top {0} lines.".format(lines_to_keep))
                lines = []
                for i in range(lines_to_keep):
                    lines.append(f.readline())
        except (IOError, OSError) as err:
            debug("{0}".format(err, xbmc.LOGERROR))
        else:
            try:
                debug("Removing all log contents.")
                with open(self.logpath, "w") as f:
                    debug("Restoring saved log contents.")
                    f.writelines(lines)
            except (IOError, OSError) as err:
                debug("{0}".format(err, xbmc.LOGERROR))
            else:
                return self.get()

    def clear(self):
        """
        Erase the contents of the log file.

        :rtype: unicode
        :return: An empty string if clearing succeeded.
        """
        try:
            debug("Clearing log file contents.")
            with open(self.logpath, "r+") as f:
                f.truncate()
        except (IOError, OSError) as err:
            debug("{0}".format(err, xbmc.LOGERROR))
        else:
            return self.get()

    def get(self):
        """
        Retrieve the contents of the log file. Creates a new log if none is found.

        :rtype: unicode
        :return: The contents of the log file.
        """
        try:
            debug("Retrieving log file contents.")
            with open(self.logpath, "a+") as f:
                contents = f.read()
        except (IOError, OSError) as err:
            debug("{0}".format(err, xbmc.LOGERROR))
        else:
            return contents


def anonymize_path(path):
    """
    :type path: unicode
    :param path: The network path containing credentials that need to be stripped.
    :rtype: unicode
    :return: The network path without the credentials.
    """
    if "://" in path:
        debug(u"Anonymizing {path}".format(path=path.decode("utf-8")))
        # Look for anything matching a protocol followed by credentials
        # This regex assumes there is no @ in the remainder of the path
        regex = u"^(?P<protocol>smb|nfs|afp|upnp|http|https):\/\/(.+:.+@)?(?P<path>[^@]+?)$"
        results = re.match(regex, path, flags=re.I | re.U).groupdict()

        # Keep only the protocol and the actual path
        path = u"{protocol}://{path}".format(protocol=results["protocol"].decode("utf-8"), path=results["path"].decode("utf-8"))
        debug(u"Result: {newpath}".format(newpath=path.decode("utf-8")))

    return path


def get_free_disk_space(path):
    """Determine the percentage of free disk space.

    :type path: unicode
    :param path: The path to the drive to check. This can be any path of any depth on the desired drive.
    :rtype: float
    :return: The percentage of free space on the disk; 100% if errors occur.
    """
    percentage = float(100)
    debug("Checking for disk space on path: {0}".format(path))
    if xbmcvfs.exists(path.encode("utf-8")):
        if xbmc.getCondVisibility("System.Platform.Windows"):
            debug("We are checking disk space from a Windows file system")
            debug("The path to check is {0}".format(path))

            if "://" in path:
                debug("We are dealing with network paths")
                debug("Extracting information from share {0}".format(path))

                regex = "(?P<type>smb|nfs|afp)://(?:(?P<user>.+):(?P<pass>.+)@)?(?P<host>.+?)/(?P<share>[^\/]+).*$"
                pattern = re.compile(regex, flags=re.I | re.U)
                match = pattern.match(path)
                try:
                    share = match.groupdict()
                    debug("Protocol: {0}, User: {1}, Password: {2}, Host: {3}, Share: {4}".format(
                          share["type"], share["user"], share["pass"], share["host"], share["share"]))
                except KeyError as ke:
                    debug("Could not parse {0} from {1}.".format(ke, path), xbmc.LOGERROR)
                    return percentage

                debug("Creating UNC paths so Windows understands the shares")
                path = os.path.normcase(os.sep + os.sep + share["host"] + os.sep + share["share"])
                debug("UNC path: {0}".format(path))
                debug("If checks fail because you need credentials, please mount the share first")
            else:
                debug("We are dealing with local paths")

            if not isinstance(path, unicode):
                debug("Converting path to unicode for disk space checks")
                path = path.decode("mbcs")
                debug("New path: {0}".format(path))

            bytes_total = c_ulonglong(0)
            bytes_free = c_ulonglong(0)
            windll.kernel32.GetDiskFreeSpaceExW(c_wchar_p(path), byref(bytes_free), byref(bytes_total), None)

            try:
                percentage = float(bytes_free.value) / float(bytes_total.value) * 100
                debug("Hard disk check results:")
                debug("Bytes free: {0}".format(bytes_free.value))
                debug("Bytes total: {0}".format(bytes_total.value))
            except ZeroDivisionError:
                notify(translate(32511), 15000, level=xbmc.LOGERROR)
        else:
            debug("We are checking disk space from a non-Windows file system")
            debug("Stripping {0} of all redundant stuff.".format(path))
            path = os.path.normpath(path)
            debug("The path now is {0}".format(path))

            try:
                diskstats = os.statvfs(path)
                percentage = float(diskstats.f_bfree) / float(diskstats.f_blocks) * 100
                debug("Hard disk check results:")
                debug("Bytes free: {0}".format(diskstats.f_bfree))
                debug("Bytes total: {0}".format(diskstats.f_blocks))
            except OSError as ose:
                # TODO: Linux cannot check remote share disk space yet
                # notify(translate(32512), 15000, level=xbmc.LOGERROR)
                notify(translate(32524), 15000, level=xbmc.LOGERROR)
                debug("Error accessing {0}: {1}".format(path, ose))
            except ZeroDivisionError:
                notify(translate(32511), 15000, level=xbmc.LOGERROR)
    else:
        notify(translate(32513), 15000, level=xbmc.LOGERROR)

    debug("Free space: {0:.2f}%".format(percentage))
    return percentage


def disk_space_low():
    """Check whether the disk is running low on free space.

    :rtype: bool
    :return: True if disk space is below threshold (set through addon settings), False otherwise.
    """
    return get_free_disk_space(get_setting(disk_space_check_path)) <= get_setting(disk_space_threshold)


def translate(msg_id):
    """
    Retrieve a localized string by id.

    :type msg_id: int
    :param msg_id: The id of the localized string.
    :rtype: unicode
    :return: The localized string. Empty if msg_id is not an integer.
    """
    return ADDON.getLocalizedString(msg_id) if isinstance(msg_id, int) else ""


def notify(message, duration=5000, image=ADDON_ICON, level=xbmc.LOGDEBUG, sound=True):
    """
    Display a Kodi notification and log the message.

    :type message: unicode
    :param message: the message to be displayed (and logged).
    :type duration: int
    :param duration: the duration the notification is displayed in milliseconds (defaults to 5000)
    :type image: unicode
    :param image: the path to the image to be displayed on the notification (defaults to ``icon.png``)
    :type level: int
    :param level: (Optional) the log level (supported values are found at xbmc.LOG...)
    :type sound: bool
    :param sound: (Optional) Whether or not to play a sound with the notification. (defaults to ``True``)
    """
    if message:
        debug(message, level)
        if get_setting(notifications_enabled) and not (get_setting(notify_when_idle) and xbmc.Player().isPlaying()):
            xbmcgui.Dialog().notification(ADDON_NAME.encode("utf-8"), message.encode("utf-8"), image.encode("utf-8"),
                                          duration, sound)


def debug(message, level=xbmc.LOGDEBUG):
    """
    Write a debug message to xbmc.log

    :type message: unicode
    :param message: the message to log
    :type level: int
    :param level: (Optional) the log level (supported values are found at xbmc.LOG...)
    """
    if get_setting(debugging_enabled):
        for line in message.splitlines():
            xbmc.log(msg="{0}: {1}".format(ADDON_NAME, line), level=level)
