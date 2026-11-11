<h1 align="center">KemonoDownloader</h1>

<div align="center">
  <img src="https://raw.githubusercontent.com/VoxDroid/KemonoDownloader/refs/heads/main/assets/img/KemonoDownloader.png" alt="Kemono Downloader" width="300"/>
</div>

<br>

* ### This is a Personal Fork Using 100% AI, I use it myself so it should be functional, but be aware anyway. Feel free to report bugs, though I am lazy.<br> 
# Additions:<br>
* Last-downloaded tracking: each post shows its publish date and the date its files were last downloaded, with the creator's most recent date next to the post count.<br>
* File and Post filtering, they can be used in many combinations, number skipped and by what displayed in run summary. The ammount of filters has grown beyond being worth listing here.<br>
* 'Search by' row for the post search bar (Title, Filenames, Description, Tags).<br>
* Adjustable folder names via templates w/ the same placeholder style as Filenames.<br> 
* Customizable skip post folder option for low-image-count posts.<br>
  * Posts with a number of files less than or equal to the selected value will have their files saved directly in the creator folder instead of creating a separate subfolder for that post.<br>
    * Option to download posts with and archive file to a subfolder regardless of 'Skip Post Folder' value.<br>
* Multi-URL input: paste one creator or post URL per line to add several to the queue at once.<br>
  * Pasted post links are normalized to their creator, and only the linked posts are auto-selected.<br>
* 'Data Directory' setting: keeps the app's own working files (thumbnail cache, databases) out of the Save Directory.<br>
* Filename templates: Split into two, 'In Post Folder' and 'In Creator Folder', using placeholders such as `{file_number}`, `{post_id}`, `{post_date}`, `{file_index}`, `{creator_name}` and `{service}`.<br>
* 'Dedup when filename is taken' (Off/On): saves a second file as `name_1`, `name_2` instead of overwriting it.<br>
* 'Open Folder' button beside the run controls: opens the creator folder of the run in flight, greyed out until that folder exists.<br>

# Changes:<br>
* Creator Downloader is now the first tab and defaults on launch.<br>
* Removed the intro splash screen and the automatic update check; Settings and the footer now link to the main repo instead.<br>
* Removed Fast Mode; batch downloading is handled by the multi-creator queue.<br>
* Toggle boxes swapped from checked to unchecked by default.<br>
* Changed retry timer from flat 1sec to an exponential (1,2,4,8 etc. capping at 30sec) to avoid hammering the API for no reason.<br>
* Double-click a post in the list to preview its thumbnail, replacing the eye button.<br>
* Removed 'Rename & Sort by File order'; the number in front of each file now comes from the filename template itself.<br>
* Filename and folder-name templates are plain text boxes now, with no preset dropdown.<br>
* Filters now re-apply to the loaded post list as you change them, with no refetch needed.<br>
* Download progress moved into its own 'Run Summary' group, with separate 'Skipped Posts' and 'Skipped Files' counter rows.<br>
* Downloads are written as `.part` and renamed when finished, so a cancelled or failed download leaves nothing behind.<br>
* Posts save straight into the Save Directory; the 'Folder Name' setting and the 'Open Directory' button are gone.<br>
* 'Apply Changes' is generated from your settings instead of a hand-filled list, so newer settings appear in the prompt on their own.<br>
* Cancelling a fetch keeps the posts already loaded instead of clearing the list.<br>

# TODO:<br>
* Save feature that saves current 'Creator Downloader' configuration.
* 'Image' 'Video' bulk filetype presets.

# Support OG DEV:<br>
**Developed by VoxDroid** | **Fork by Deepseek Flash lol**<br>
[GitHub](https://github.com/VoxDroid) | [Ko-fi](https://ko-fi.com/izeno)

# AI Written Rundown:<br>
**Just incase I missed something above, the program is damn near unrecognizable from main.**

*AI replaces this & writes whatever they want here.*