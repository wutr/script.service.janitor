#!/usr/bin/python
# -*- coding: utf-8 -*-

import xbmcaddon
import xbmcgui
import utils

# Addon info
__addon__ = xbmcaddon.Addon(utils.__addonID__)


def reset_exclusions():
    """
    Reset all user-set exclusion paths to blanks.
    :return:
    """
    if xbmcgui.Dialog().yesno(utils.translate(32604), utils.translate(32610), utils.translate(32607)):
        __addon__.setSetting(id="exclusion1", value="")
        __addon__.setSetting(id="exclusion2", value="")
        __addon__.setSetting(id="exclusion3", value="")
        __addon__.setSetting(id="exclusion4", value="")
        __addon__.setSetting(id="exclusion5", value="")

reset_exclusions()
