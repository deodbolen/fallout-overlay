"""Desktop Trash operations through GVfs, including other mounted volumes."""
import os


def operation(callback):
    import gi
    gi.require_version('Gio','2.0')
    from gi.repository import Gio, GLib
    try: return callback(Gio)
    except GLib.Error as error: raise ValueError(error.message) from None


def entries():
    def collect(Gio):
        root=Gio.File.new_for_uri('trash:///')
        iterator=root.enumerate_children('standard::name,standard::display-name,standard::type,trash::orig-path',
                                         Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,None)
        result=[]
        try:
            while True:
                info=iterator.next_file(None)
                if info is None: break
                original=info.get_attribute_byte_string('trash::orig-path')
                result.append({'uri':root.get_child(info.get_name()).get_uri(),
                               'name':info.get_display_name(),
                               'directory':info.get_file_type()==Gio.FileType.DIRECTORY,
                               'original':os.fsdecode(original) if original else ''})
        finally: iterator.close(None)
        return sorted(result,key=lambda item:(not item['directory'],item['name'].casefold(),item['uri']))
    return operation(collect)


def restore(item):
    if not item['original'] or not os.path.isabs(item['original']):
        raise ValueError('The original location is unavailable; this item cannot be restored.')
    def move(Gio):
        source=Gio.File.new_for_uri(item['uri'])
        destination=Gio.File.new_for_path(item['original'])
        # NONE preserves files already occupying the original path.
        source.move(destination,Gio.FileCopyFlags.NONE,None,None,None)
    operation(move)


def delete(item):
    # Deleting a top-level Trash URI lets GVfs remove the entire trashed folder
    # and its metadata, without following symlinks into live directories.
    operation(lambda Gio:Gio.File.new_for_uri(item['uri']).delete(None))


def empty(items):
    for item in items: delete(item)
