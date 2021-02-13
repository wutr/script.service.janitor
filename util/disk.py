#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
from ctypes import *

import xbmc
import xbmcvfs

from util.logging.kodi import debug, notify, translate
from util.settings import *


def get_free_disk_space(path):
    """Determine the percentage of free disk space.

    :type path: unicode
    :param path: The path to the drive to check. This can be any path of any depth on the desired drive.
    :rtype: float
    :return: The percentage of free space on the disk; 100% if errors occur.
    """
    percentage = float(100)
    debug(f"Checking for disk space on path: {path}")
    if xbmcvfs.exists(path.encode()):
        if xbmc.getCondVisibility("System.Platform.Windows"):
            debug("We are checking disk space from a Windows file system")
            debug(f"The path to check is {path}")

            if "://" in path:
                debug("We are dealing with network paths")
                debug(f"Extracting information from share {path}")

                regex = "(?P<type>smb|nfs|afp)://(?:(?P<user>.+):(?P<pass>.+)@)?(?P<host>.+?)/(?P<share>[^\/]+).*$"
                pattern = re.compile(regex, flags=re.I | re.U)
                match = pattern.match(path)
                try:
                    share = match.groupdict()
                    debug(f"Protocol: {share['type']}, User: {share['user']}, Password: {share['pass']}, Host: {share['host']}, Share: {share['share']}")
                except KeyError as ke:
                    debug(f"Could not parse {ke} from {path}.", xbmc.LOGERROR)
                    return percentage

                debug("Creating UNC paths so Windows understands the shares")
                path = os.path.normcase(os.sep + os.sep + share["host"] + os.sep + share["share"])
                debug(f"UNC path: {path}")
                debug("If checks fail because you need credentials, please mount the share first")
            else:
                debug("We are dealing with local paths")

            bytes_total = c_ulonglong(0)
            bytes_free = c_ulonglong(0)
            windll.kernel32.GetDiskFreeSpaceExW(c_wchar_p(path), byref(bytes_free), byref(bytes_total), None)

            try:
                percentage = float(bytes_free.value) / float(bytes_total.value) * 100
                debug("Hard disk check results:")
                debug(f"Bytes free: {bytes_free.value}")
                debug(f"Bytes total: {bytes_total.value}")
            except ZeroDivisionError:
                notify(translate(32511), 15000, level=xbmc.LOGERROR)
        else:
            debug("We are checking disk space from a non-Windows file system")
            debug(f"Stripping {path} of all redundant stuff.")
            path = os.path.normpath(path)
            debug(f"The path now is {path}")

            try:
                diskstats = os.statvfs(path)
                percentage = float(diskstats.f_bfree) / float(diskstats.f_blocks) * 100
                debug("Hard disk check results:")
                debug(f"Bytes free: {diskstats.f_bfree}")
                debug(f"Bytes total: {diskstats.f_blocks}")
            except OSError as ose:
                # TODO: Linux cannot check remote share disk space yet
                # notify(translate(32512), 15000, level=xbmc.LOGERROR)
                notify(translate(32524), 15000, level=xbmc.LOGERROR)
                debug(f"Error accessing {path}: {ose}")
            except ZeroDivisionError:
                notify(translate(32511), 15000, level=xbmc.LOGERROR)
    else:
        notify(translate(32513), 15000, level=xbmc.LOGERROR)

    debug(f"Free space: {percentage:.2f}%")
    return percentage


def disk_space_low():
    """Check whether the disk is running low on free space.

    :rtype: bool
    :return: True if disk space is below threshold (set through addon settings), False otherwise.
    """
    return get_free_disk_space(get_value(disk_space_check_path)) <= get_value(disk_space_threshold)

