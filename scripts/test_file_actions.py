import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from file_actions import copy_file, move_file, destination, new_name, compress_file, file_info, create_entry
from browser import Navigator
from unittest.mock import Mock

class FileActionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.source=self.root/'file with spaces.txt'; self.source.write_text('preserve content')
        self.folder=self.root/'destination'; self.folder.mkdir()
    def tearDown(self): self.temp.cleanup()
    def test_create_file_directory_and_preserve_existing(self):
        file=create_entry(self.folder,'new file.txt','File')
        self.assertEqual(file.read_bytes(),b'')
        folder=create_entry(self.folder,'new folder','Directory')
        self.assertTrue(folder.is_dir())
        file.write_text('keep')
        with self.assertRaises(FileExistsError): create_entry(self.folder,file.name,'File')
        self.assertEqual(file.read_text(),'keep')
        with self.assertRaises(FileExistsError): create_entry(self.folder,folder.name,'Directory')
        for name in ('','..','../outside'):
            with self.assertRaises(ValueError): create_entry(self.folder,name,'File')

    def test_cancel_new_entry_creates_nothing(self):
        navigator=Navigator(Mock()); navigator.menu=Mock(return_value=2)
        navigator.new_entry(self.folder)
        self.assertEqual(list(self.folder.iterdir()),[])

    def test_copy_and_move(self):
        copied=copy_file(self.source,destination(self.source,str(self.folder)))
        self.assertEqual(copied.read_text(),self.source.read_text())
        renamed=move_file(self.source,new_name(self.source,'renamed.txt'))
        self.assertFalse(self.source.exists()); self.assertEqual(renamed.read_text(),'preserve content')
    def test_existing_destinations_are_preserved(self):
        target=self.folder/self.source.name; target.write_text('existing')
        for function in (copy_file,move_file):
            with self.assertRaises(FileExistsError): function(self.source,target)
            self.assertEqual(target.read_text(),'existing'); self.assertTrue(self.source.exists())
    def test_cross_filesystem_move(self):
        with patch('file_actions.os.link',side_effect=OSError(errno.EXDEV,'cross-device')):
            target=move_file(self.source,self.folder/self.source.name)
        self.assertEqual(target.read_text(),'preserve content'); self.assertFalse(self.source.exists())
    def test_compress_does_not_replace_archive(self):
        archive=compress_file(self.source)
        with zipfile.ZipFile(archive) as zipped:
            self.assertEqual(zipped.read(self.source.name),b'preserve content')
        original=archive.read_bytes()
        with self.assertRaises(FileExistsError): compress_file(self.source)
        self.assertEqual(archive.read_bytes(),original)
    def test_symlink_copy_and_info(self):
        link=self.root/'link'; link.symlink_to('file with spaces.txt')
        copy=copy_file(link,self.folder/'link')
        self.assertTrue(copy.is_symlink())
        self.assertTrue(any('Symbolic link' in line for line in file_info(link)))
    def test_invalid_name_and_destination(self):
        for name in ('','..','../oops'):
            with self.assertRaises(ValueError): new_name(self.source,name)
        with self.assertRaises(ValueError): destination(self.source,'missing')
        self.assertEqual(destination(self.source,'destination'),self.folder/self.source.name)
    def test_file_enter_opens_document(self):
        navigator=Navigator(Mock()); navigator.open_document=Mock()
        navigator.activate('home',0,[(self.source,1,False)])
        navigator.open_document.assert_called_once_with(self.source)
    def test_text_document_opens_new_editor_session(self):
        navigator=Navigator(Mock()); navigator.launch=Mock()
        navigator.open_document(self.source)
        navigator.launch.assert_called_once_with('editor','Nano: '+self.source.name,path=str(self.source),cwd=str(self.source.parent))

    def test_binary_document_opens_external_viewer(self):
        binary=self.root/'image.png'; binary.write_bytes(b'\x89PNG\x00')
        navigator=Navigator(Mock()); navigator.launch=Mock()
        with patch('browser.subprocess.Popen') as launch, patch.object(navigator, 'hide_for_application') as hide:
            navigator.open_document(binary)
            hide.assert_called_once()
            self.assertEqual(launch.call_args.args[0],['xdg-open',str(binary)])
        navigator.launch.assert_not_called()

    def test_gui_and_custom_application_arguments(self):
        navigator=Navigator(Mock())
        executable=self.root/'application with spaces'
        executable.write_text('#!/bin/sh\n'); executable.chmod(0o700)
        with patch('browser.subprocess.Popen') as launch, patch.object(navigator, 'hide_for_application') as hide:
            navigator.open_gui(self.source)
            self.assertEqual(launch.call_args.args[0],['xdg-open',str(self.source)])
            navigator.open_gui(self.source,str(executable))
            self.assertEqual(launch.call_args.args[0],[str(executable),str(self.source)])
            executable.chmod(0o600)
            with self.assertRaises(ValueError): navigator.open_gui(self.source,str(executable))
            with self.assertRaises(ValueError): navigator.open_gui(self.source,'mousepad')
            self.assertEqual(launch.call_count,2)
            self.assertEqual(hide.call_count,2)

    def test_open_with_cancel_does_not_launch(self):
        navigator=Navigator(Mock()); navigator.menu=Mock(return_value=None)
        with patch('browser.subprocess.Popen') as launch:
            navigator.open_with(self.source)
            launch.assert_not_called()

    def test_cancel_and_scp_do_not_change_file(self):
        navigator=Navigator(Mock())
        for choice in (None,3,10):
            navigator.menu=Mock(return_value=choice); navigator.file_actions(self.source)
            self.assertEqual(self.source.read_text(),'preserve content')

if __name__=='__main__': unittest.main()
