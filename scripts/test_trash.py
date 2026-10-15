import unittest
from unittest.mock import Mock,patch
from browser import Navigator
import trash_store


class TrashTests(unittest.TestCase):
    def setUp(self):
        self.nav=Navigator(Mock())
        self.item={'uri':'trash:///folder','name':'folder','directory':True,'original':'/home/user/folder'}

    def test_restore_selected_folder(self):
        self.nav.menu=Mock(return_value=0)
        with patch('trash_store.restore') as restore,patch('trash_store.delete') as delete:
            self.nav.activate('trash',1,[self.item])
            restore.assert_called_once_with(self.item)
            delete.assert_not_called()

    def test_cancel_never_deletes(self):
        for index,answers in ((0,[0]),(1,[1,0]),(1,[2])):
            self.nav.menu=Mock(side_effect=answers)
            with patch('trash_store.delete') as delete,patch('trash_store.empty') as empty:
                self.nav.activate('trash',index,[self.item])
                delete.assert_not_called(); empty.assert_not_called()

    def test_confirmed_empty_uses_displayed_items(self):
        self.nav.menu=Mock(return_value=1)
        with patch('trash_store.empty') as empty:
            self.nav.activate('trash',0,[self.item])
            empty.assert_called_once_with([self.item])

    def test_restore_does_not_overwrite_existing_destination(self):
        gio=Mock()
        gio.FileCopyFlags.NONE=0
        with patch('trash_store.operation',side_effect=lambda callback:callback(gio)):
            trash_store.restore(self.item)
        gio.File.new_for_uri.return_value.move.assert_called_once_with(
            gio.File.new_for_path.return_value,0,None,None,None)


if __name__=='__main__': unittest.main()
