#!/usr/bin/python
# -*- coding: utf-8 -*-

import json
import sys

import xbmcgui
from xbmcgui import DialogProgress, Dialog

from util import exclusions
from util.addon_info import ADDON_NAME, ADDON_ID
from util.disk import *
from util.logging.janitor import LogViewerDialog, Log
from util.logging.kodi import debug
from util.settings import *

MOVIES = "movies"
MUSIC_VIDEOS = "musicvideos"
TVSHOWS = "episodes"
KNOWN_VIDEO_TYPES = (MOVIES, MUSIC_VIDEOS, TVSHOWS)


class Database(object):
    """TODO: Docstring
    """
    movie_filter_fields = ["title", "plot", "plotoutline", "tagline", "votes", "rating", "time", "writers",
                           "playcount", "lastplayed", "inprogress", "genre", "country", "year", "director",
                           "actor", "mpaarating", "top250", "studio", "hastrailer", "filename", "path", "set",
                           "tag", "dateadded", "videoresolution", "audiochannels", "videocodec", "audiocodec",
                           "audiolanguage", "subtitlelanguage", "videoaspect", "playlist"]
    episode_filter_fields = ["title", "tvshow", "plot", "votes", "rating", "time", "writers", "airdate",
                             "playcount", "lastplayed", "inprogress", "genre", "year", "director", "actor",
                             "episode", "season", "filename", "path", "studio", "mpaarating", "dateadded",
                             "videoresolution", "audiochannels", "videocodec", "audiocodec", "audiolanguage",
                             "subtitlelanguage", "videoaspect", "playlist"]
    musicvideo_filter_fields = ["title", "genre", "album", "year", "artist", "filename", "path", "playcount",
                                "lastplayed", "time", "director", "studio", "plot", "dateadded",
                                "videoresolution", "audiochannels", "videocodec", "audiocodec", "audiolanguage",
                                "subtitlelanguage", "videoaspect", "playlist"]
    supported_filter_fields = {
        TVSHOWS: episode_filter_fields,
        MOVIES: movie_filter_fields,
        MUSIC_VIDEOS: musicvideo_filter_fields
    }
    methods = {
        TVSHOWS: "VideoLibrary.GetEpisodes",
        MOVIES: "VideoLibrary.GetMovies",
        MUSIC_VIDEOS: "VideoLibrary.GetMusicVideos"
    }
    properties = {
        TVSHOWS: ["file", "showtitle"],
        MOVIES: ["file", "title"],
        MUSIC_VIDEOS: ["file", "artist"]
    }

    def __init__(self):
        """TODO: Docstring
        """
        self.settings = {}

    def prepare_query(self, video_type):
        """TODO: Docstring
        :rtype dict:
        :return the complete JSON-RPC request to be sent
        """
        # Always refresh the user's settings before preparing a JSON-RPC query
        self.settings = reload_preferences()

        # A non-exhaustive list of pre-defined filters to use during JSON-RPC requests
        # These are possible conditions that must be met before a video can be deleted
        by_playcount = {"field": "playcount", "operator": "greaterthan", "value": "0"}
        by_date_played = {"field": "lastplayed", "operator": "notinthelast", "value": f"{self.settings[expire_after]:f}"}
        by_minimum_rating = {"field": "rating", "operator": "lessthan", "value": f"{self.settings[minimum_rating]:f}"}
        by_no_rating = {"field": "rating", "operator": "isnot", "value": "0"}
        by_progress = {"field": "inprogress", "operator": "false", "value": ""}
        by_exclusion1 = {"field": "path", "operator": "doesnotcontain", "value": self.settings[exclusion1]}
        by_exclusion2 = {"field": "path", "operator": "doesnotcontain", "value": self.settings[exclusion2]}
        by_exclusion3 = {"field": "path", "operator": "doesnotcontain", "value": self.settings[exclusion3]}
        by_exclusion4 = {"field": "path", "operator": "doesnotcontain", "value": self.settings[exclusion4]}
        by_exclusion5 = {"field": "path", "operator": "doesnotcontain", "value": self.settings[exclusion5]}

        # link settings and filters together
        settings_and_filters = [
            (self.settings[enable_expiration], by_date_played),
            (self.settings[clean_when_low_rated], by_minimum_rating),
            (self.settings[not_in_progress], by_progress),
            (self.settings[exclusion_enabled] and self.settings[exclusion1] != "", by_exclusion1),
            (self.settings[exclusion_enabled] and self.settings[exclusion2] != "", by_exclusion2),
            (self.settings[exclusion_enabled] and self.settings[exclusion3] != "", by_exclusion3),
            (self.settings[exclusion_enabled] and self.settings[exclusion4] != "", by_exclusion4),
            (self.settings[exclusion_enabled] and self.settings[exclusion5] != "", by_exclusion5)
        ]

        # Only check not rated videos if checking for video ratings at all
        if self.settings[clean_when_low_rated]:
            settings_and_filters.append((self.settings[ignore_no_rating], by_no_rating))

        enabled_filters = [by_playcount]
        for setting, filter in settings_and_filters:
            if setting and filter["field"] in self.supported_filter_fields[video_type]:
                enabled_filters.append(filter)

        debug(f"[{self.methods[video_type]}] Filters enabled: {enabled_filters}")

        filters = {"and": enabled_filters}

        request = {
            "jsonrpc": "2.0",
            "method": self.methods[video_type],
            "params": {
                "properties": self.properties[video_type],
                "filter": filters
            },
            "id": 1
        }

        return request

    @staticmethod
    def check_errors(response):
        """TODO: Docstring
        """
        result = json.loads(response)

        try:
            error = result["error"]
            debug(f"An error occurred. {error}", xbmc.LOGERROR)
            raise ValueError(f"[{error['data']['method']}]: {error['data']['stack']['message']}")
        except KeyError as ke:
            if "error" in str(ke):
                pass  # no error
            else:
                raise KeyError(f"Something went wrong while parsing errors from JSON-RPC. I couldn't find {ke}") from ke

        # No errors, so return actual response
        return result["result"]

    def execute_query(self, query):
        """TODO: Docstring
        """
        response = xbmc.executeJSONRPC(json.dumps(query))
        debug(f"[{query['method']}] Response: {response}")

        return self.check_errors(response)

    def get_expired_videos(self, video_type):
        """
        Find videos in the Kodi library that have been watched.

        Respects any other conditions user enables in the addon's settings.

        :type video_type: unicode
        :param video_type: The type of videos to find (one of the globals MOVIES, MUSIC_VIDEOS or TVSHOWS).
        :rtype: list
        :return: A list of expired videos, along with a number of extra attributes specific to the video type.
        """

        # TODO: split up this method into a pure database query and let the Janitor class handle the rest

        video_types = (TVSHOWS, MOVIES, MUSIC_VIDEOS)
        setting_types = (clean_tv_shows, clean_movies, clean_music_videos)

        for type, setting in zip(video_types, setting_types):
            if type == video_type and get_value(setting):
                # Do the actual work here
                query = self.prepare_query(video_type)
                result = self.execute_query(query)
                totals = int(result["limits"]["total"])

                try:
                    debug(f"Found {totals} watched {video_type} matching your conditions")
                    debug(f"JSON Response: {result}")
                    for video in result[video_type]:
                        # Gather all properties and add it to this video's information
                        temp = []
                        for p in self.properties[video_type]:
                            temp.append(video[p])
                        yield temp
                except KeyError as ke:
                    if video_type in str(ke):
                        pass  # no expired videos found
                    else:
                        raise KeyError(f"Could not find key {ke} in response.")
                finally:
                    debug("Breaking the loop")
                    break  # Stop looping after the first match for video_type

    def get_video_sources(self, limits=None, sort=None):
        """
        Retrieve the user configured video sources from Kodi

        To limit or sort the results, you may supply these in the form of a dict.
        See List.Sort and List.Limits objects on the JSON-RPC API specifications:
        https://kodi.wiki/view/JSON-RPC_API/

        :param limits: The limits to impose on JSON-RPC
        :type limits: dict
        :param sort: The sorting options for JSON-RPC
        :type sort: dict
        :return: The user configured video sources
        :rtype: dict
        """

        if sort is None:
            sort = {}
        if limits is None:
            limits = {}

        request = {
            "jsonrpc": "2.0",
            "method": "Files.GetSources",
            "params": {
                "media": "video",
                "limits": limits,
                "sort": sort
            },
            "id": 1
        }

        return self.execute_query(request)


class Janitor(object):
    """
    The Cleaner class allows users to clean up their movie, TV show and music video collection by removing watched
    items. The user can apply a number of conditions to cleaning, such as limiting cleaning to files with a given
    rating, excluding a particular folder or only cleaning when a particular disk is low on disk space.

    The main method to call is the ``clean()`` method. This method will invoke the subsequent checks and (re)move
    your videos. Upon completion, you will receive a short summary of the cleaning results.

    *Example*
      ``summary = Cleaner().clean()``
    """

    # Constants to ensure correct JSON-RPC requests for Kodi
    CLEANING_TYPE_MOVE = "0"
    CLEANING_TYPE_DELETE = "1"
    DEFAULT_ACTION_CLEAN = "0"
    DEFAULT_ACTION_LOG = "1"

    STATUS_SUCCESS = 1
    STATUS_FAILURE = 2
    STATUS_ABORTED = 3

    progress = DialogProgress()
    monitor = xbmc.Monitor()
    silent = True
    exit_status = STATUS_SUCCESS
    total_expired = 0

    def __init__(self):
        debug(f"{ADDON.getAddonInfo('name')} version {ADDON.getAddonInfo('version')} loaded.")
        self.db = Database()

    def user_aborted(self):
        """
        Test if the progress dialog has been canceled by the user. If the cleaner was started as a service this will
        always return False
        :rtype: bool
        :return: True if the user cancelled cleaning, False otherwise.
        """
        if self.silent:
            return False
        elif self.progress.iscanceled():
            debug("User canceled.", xbmc.LOGWARNING)
            self.exit_status = self.STATUS_ABORTED
            return True

    def show_progress(self):
        """
        Toggle the progress dialog on. Use before calling the cleaning method.
        """
        self.silent = False

    def hide_progress(self):
        """
        Toggle the progress dialog off. Use before calling the cleaning method.
        """
        self.silent = True

    def process_file(self, file_name, title):
        """Handle the cleaning of a video file, either via deletion or moving to another location

        :param file_name:
        :type file_name:
        :param title:
        :type title:
        :return:
        :rtype:
        """
        count, cleaned_files = 0, []
        if get_value(cleaning_type) == self.CLEANING_TYPE_MOVE:
            # No destination set, prompt user to set one now
            if get_value(holding_folder) == "":
                if Dialog().yesno(ADDON_NAME, translate(32521)):
                    xbmc.executebuiltin(f"Addon.OpenSettings({ADDON_ID})")
                    self.exit_status = self.STATUS_ABORTED
                else:
                    self.exit_status = self.STATUS_FAILURE
                return cleaned_files
            if get_value(create_subdirs):
                title = re.sub(r"[\\/:*?\"<>|]+", "_", title)
                new_path = os.path.join(get_value(holding_folder), title)
            else:
                new_path = get_value(holding_folder)
            if move_file(file_name, new_path):
                debug("File(s) moved successfully.")
                count += 1
                if is_stacked_file(file_name) and len(split_stack(file_name)) > 1:
                    cleaned_files.extend(split_stack(file_name))
                else:
                    cleaned_files.append(file_name)
                self.clean_extras(file_name, new_path)
                self.delete_empty_folders(os.path.dirname(file_name))
                self.exit_status = self.STATUS_SUCCESS
                return cleaned_files
            else:
                debug("Moving errors occurred. Skipping related files and directories.", xbmc.LOGWARNING)
                # TODO: Fix this dialog now that the first line can span multiple lines
                Dialog().ok(*map(translate, (32611, 32612, 32613, 32614)))
                self.exit_status = self.STATUS_FAILURE
                return cleaned_files
        elif get_value(cleaning_type) == self.CLEANING_TYPE_DELETE:
            if delete_file(file_name):
                debug("File(s) deleted successfully.")
                count += 1
                if is_stacked_file(file_name) and len(split_stack(file_name)) > 1:
                    cleaned_files.extend(split_stack(file_name))
                else:
                    cleaned_files.append(file_name)
                self.clean_extras(file_name)
                self.delete_empty_folders(os.path.dirname(file_name))
                self.exit_status = self.STATUS_SUCCESS
            else:
                debug("Errors occurred during file deletion", xbmc.LOGWARNING)
                self.exit_status = self.STATUS_FAILURE

            return cleaned_files

    def clean_category(self, video_type):
        """
        Clean all watched videos of the provided type.

        :type video_type: unicode
        :param video_type: The type of videos to clean (one of TVSHOWS, MOVIES, MUSIC_VIDEOS).
        :rtype: (list, int, int)
        :return: A list of the filenames that were cleaned, as well as the number of files cleaned and the return status.
        """
        type_translation = {MOVIES: translate(32626), MUSIC_VIDEOS: translate(32627), TVSHOWS: translate(32628)}

        if not self.silent:
            # Cleaning <video type>
            self.progress.update(0, translate(32629).format(type=type_translation[video_type]))
            self.monitor.waitForAbort(1)

        # Reset counters
        cleaned_files = []
        progress_percent = 0
        count = 0

        for filename, title in self.db.get_expired_videos(video_type):
            # Check at the beginning of each loop if the user pressed cancel
            # We do not want to cancel cleaning in the middle of a cycle to prevent issues with leftovers
            if not self.user_aborted():
                if file_exists(filename) and not is_hardlinked(filename):
                    cleaned_files = self.process_file(filename, title)
                    count += len(cleaned_files)
                else:
                    debug(f"Not cleaning {filename}. It may have already been removed.", xbmc.LOGWARNING)

                if not self.silent:
                    # TODO: this now fails because get_expired_videos is a generator
                    # TODO: maybe we'd better just display the video file that is being cleaned
                    try:
                        # TODO: Incorporate number of video types being cleaned into the calculation
                        progress_percent += 1 / self.total_expired * 100
                    except ZeroDivisionError:
                        progress_percent += 0  # No videos found that need cleaning

                    filenames = "\n".join(map(os.path.basename, split_stack(filename)))
                    progress_text = f"[B]{translate(32618).format(type=video_type)}[/B]\n{filenames}"
                    self.progress.update(int(progress_percent), progress_text)
                    self.monitor.waitForAbort(2)
            else:
                debug(f"We had {self.total_expired - count} {type_translation[video_type]} left to clean.")
        else:
            if not self.silent:
                self.progress.update(0, translate(32624).format(type=type_translation[video_type]))
                self.monitor.waitForAbort(2)

        return cleaned_files, count, self.exit_status

    def clean(self):
        """
        Clean up any watched videos in the Kodi library, satisfying any conditions set via the addon settings.

        :rtype: (dict, int)
        :return: A single-line (localized) summary of the cleaning results to be used for a notification, plus a status.
        """
        debug("Starting cleaning routine.")

        if get_value(clean_when_idle) and xbmc.Player().isPlaying():
            debug("Kodi is currently playing a file. Skipping cleaning.", xbmc.LOGWARNING)
            return None, self.exit_status

        results = {}
        cleaning_results, cleaned_files = [], []
        if not get_value(clean_when_low_disk_space) or (get_value(clean_when_low_disk_space) and disk_space_low()):
            if not self.silent:
                self.progress.create(ADDON_NAME)  # TODO: Make this a standalone dialog for each video type
                self.progress.update(0)
                self.monitor.waitForAbort(2)
            for video_type in KNOWN_VIDEO_TYPES:
                if not self.user_aborted():
                    cleaned_files, count, status = self.clean_category(video_type)
                    if count > 0:
                        cleaning_results.extend(cleaned_files)
                        results[video_type] = count
            if not self.silent:
                self.progress.close()

        self.clean_library(cleaning_results)

        Log().prepend(cleaning_results)

        return results, self.exit_status

    def clean_library(self, purged_files):
        # Check if we need to perform any post-cleaning operations
        if purged_files and get_value(clean_library):
            self.monitor.waitForAbort(2)  # Sleep 2 seconds to make sure file I/O is done.

            if xbmc.getCondVisibility("Library.IsScanningVideo"):
                debug("The video library is being updated. Skipping library cleanup.", xbmc.LOGWARNING)
            else:
                xbmc.executebuiltin("XBMC.CleanLibrary(video, false)")
        else:
            debug("Cleaning Kodi library not required and/or not enabled.")

    @staticmethod
    def get_cleaning_results(details):
        """
        Create a summary from the cleaning results.

        :type details: dict
        :rtype: unicode
        :return: A comma separated summary of the cleaning results.
        """
        summary = ""

        # Localize video types
        for vid_type, amount in details.items():
            if vid_type is MOVIES:
                video_type = translate(32515)
            elif vid_type is TVSHOWS:
                video_type = translate(32516)
            elif vid_type is MUSIC_VIDEOS:
                video_type = translate(32517)
            else:
                video_type = ""

            summary += f"{amount:d} {video_type}, "

        # strip the comma and space from the last iteration and add the localized suffix
        return f"{summary.rstrip(', ')}{translate(32518)}" if summary else ""

    def delete_empty_folders(self, location):
        """
        Delete the folder if it is empty. Presence of custom file extensions can be ignored while scanning.

        To achieve this, edit the ignored file types setting in the addon settings.

        Example:
            success = delete_empty_folders(path)

        :type location: unicode
        :param location: The path to the folder to be deleted.
        :rtype: bool
        :return: True if the folder was deleted successfully, False otherwise.
        """
        if not get_value(delete_folders):
            debug("Deleting of empty folders is disabled.")
            return False

        folder = split_stack(location)[0]  # Stacked paths should have the same parent, use any
        debug(f"Checking if {folder} is empty")
        ignored_file_types = [file_ext.strip() for file_ext in get_value(ignore_extensions).split(",")]
        debug(f"Ignoring file types {ignored_file_types}")

        subfolders, files = xbmcvfs.listdir(folder)
        debug(f"Contents of {folder}:\nSubfolders: {subfolders}\nFiles: {files}")

        empty = True
        try:
            for f in files:
                _, ext = os.path.splitext(f)
                if ext and ext not in ignored_file_types:  # ensure f is not a folder and its extension is not ignored
                    debug(f"Found non-ignored file type {ext}")
                    empty = False
                    break
        except OSError as oe:
            debug(f"Error deriving file extension. Errno {oe.errno}", xbmc.LOGERROR)
            empty = False

        # Only delete directories if we found them to be empty (containing no files or filetypes we ignored)
        if empty:
            debug("Directory is empty and will be removed")
            try:
                # Recursively delete any subfolders
                for f in subfolders:
                    debug(f"Deleting file at {os.path.join(folder, f)}")
                    self.delete_empty_folders(os.path.join(folder, f))

                # Delete any files in the current folder
                for f in files:
                    debug(f"Deleting file at {os.path.join(folder, f)}")
                    xbmcvfs.delete(os.path.join(folder, f))

                # Finally delete the current folder
                return xbmcvfs.rmdir(folder)
            except OSError as oe:
                debug(f"An exception occurred while deleting folders. Errno {oe.errno}", xbmc.LOGERROR)
                return False
        else:
            debug("Directory is not empty and will not be removed")
            return False

    def clean_extras(self, source, dest_folder=None):
        """Clean files related to another file based on the user's preferences.

        Related files are files that only differ by extension, or that share a prefix in case of stacked movies.

        Examples of related files include NFO files, thumbnails, subtitles, fanart, etc.

        :type source: unicode
        :param source: Location of the file whose related files should be cleaned.
        :type dest_folder: unicode
        :param dest_folder: (Optional) The folder where related files should be moved to. Not needed when deleting.
        """
        if get_value(clean_related):
            debug("Cleaning related files.")

            path_list = split_stack(source)
            path, name = os.path.split(path_list[0])  # Because stacked movies are in the same folder, only check one
            if is_stacked_file(source):
                name = get_common_prefix(path_list)
            else:
                name, ext = os.path.splitext(name)

            debug(f"Attempting to match related files in {path} with prefix {name}")
            for extra_file in xbmcvfs.listdir(path)[1]:
                if extra_file.startswith(name):
                    debug(f"{extra_file} starts with {name}.")
                    extra_file_path = os.path.join(path, extra_file)
                    if get_value(cleaning_type) == self.CLEANING_TYPE_DELETE:
                        if extra_file_path not in path_list:
                            debug(f"Deleting {extra_file_path}.")
                            xbmcvfs.delete(extra_file_path)
                    elif get_value(cleaning_type) == self.CLEANING_TYPE_MOVE:
                        new_extra_path = os.path.join(dest_folder, os.path.basename(extra_file))
                        if new_extra_path not in path_list:
                            debug(f"Moving {extra_file_path} to {new_extra_path}.")
                            xbmcvfs.rename(extra_file_path, new_extra_path)
            debug("Finished searching for related files.")
        else:
            debug("Cleaning of related files is disabled.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "log":
        win = LogViewerDialog("JanitorLogViewer.xml", ADDON.getAddonInfo("path"))
        win.doModal()
        del win
    elif len(sys.argv) > 1 and sys.argv[1] == "reset":
        exclusions.reset()
    else:
        janitor = Janitor()
        if get_value(default_action) == janitor.DEFAULT_ACTION_LOG:
            xbmc.executebuiltin(f"RunScript({ADDON_ID}, log)")
        else:
            janitor.show_progress()
            results, return_status = janitor.clean()
            if any(results.values()):
                # Videos were cleaned. Ask the user to view the log file.
                # TODO: Listen to OnCleanFinished notifications and wait before asking to view the log
                if Dialog().yesno(translate(32514), translate(32519).format(summary=janitor.get_cleaning_results(results))):
                    xbmc.executebuiltin(f"RunScript({ADDON_ID}, log)")
            elif return_status == janitor.STATUS_ABORTED:
                # Do not show cleaning results in case user aborted, e.g. to set holding folder
                pass
            else:
                Dialog().ok(ADDON_NAME, translate(32520))
