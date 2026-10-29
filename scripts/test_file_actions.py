import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from file_actions import rename_directory, copy_file, move_file, destination, new_name, compress_file, file_info, create_entry, download_file
from browser import Navigator
from unittest.mock import Mock

class FileActionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.source=self.root/'file with spaces.txt'; self.source.write_text('preserve content')
        self.folder=self.root/'destination'; self.folder.mkdir()
    def tearDown(self): self.temp.cleanup()
    def test_scp_arguments_preserve_paths_and_support_ipv6(self):
        from ssh_manager import scp_args
        host={'name':'Server','address':'2001:db8::1','user':'alice','key':''}
        args=scp_args(self.source,host,'/shared/my files')
        self.assertEqual(args[0],'scp')
        self.assertEqual(args[-3:],['--',str(self.source),'alice@[2001:db8::1]:/shared/my files/'])
        self.assertNotIn('-O',args)
        self.assertEqual(scp_args(self.source,host,'/')[-1],'alice@[2001:db8::1]:/')
        with self.assertRaises(ValueError): scp_args(self.source,host,'')
        with self.assertRaises(ValueError): scp_args(self.source,host,'bad\npath')
        with self.assertRaises(ValueError): scp_args(self.source,host,'~/',{'path':str(self.root/'missing-key')})

    def test_download_preserves_existing_and_copies_link_contents(self):
        existing=self.folder/self.source.name; existing.write_text('keep')
        with patch('file_actions.downloads_directory',return_value=self.folder):
            target=download_file(self.source)
            self.assertEqual(target.read_text(),'preserve content')
            self.assertEqual(existing.read_text(),'keep')
            link=self.root/'linked.txt'; link.symlink_to(self.source)
            downloaded=download_file(link)
            self.assertFalse(downloaded.is_symlink())
            self.assertEqual(downloaded.read_text(),'preserve content')

    def test_transfer_menu_depends_on_data_location(self):
        navigator=Navigator.__new__(Navigator)
        navigator.tree=object()
        navigator.menu=Mock(return_value=None)
        for identity,expected in [('home','SCP'),('root','SCP'),('remote-server','Download')]:
            navigator.data_trees={identity:navigator.tree}
            navigator.file_actions(self.source)
            self.assertEqual(navigator.menu.call_args.args[1][3],expected)

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
    def test_compression_progress_shows_brand_and_propagates_errors(self):
        nav=Navigator.__new__(Navigator)
        nav.screen=Mock(); nav.screen.getmaxyx.return_value=(30,100)
        nav.draw=Mock(); nav.put=Mock()
        with patch('browser.compress_file',return_value=self.root/'result.zip'):
            self.assertEqual(nav.compress_with_progress(self.folder),self.root/'result.zip')
        rendered=' '.join(call.args[1] for call in nav.put.call_args_list)
        self.assertIn('VAULT-TEC',rendered)
        self.assertIn('COMPRESSING',rendered)
        with patch('browser.compress_file',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'): nav.compress_with_progress(self.folder)

    def test_rename_directory_preserves_contents_and_refuses_existing_target(self):
        (self.folder/'child').write_text('keep')
        existing=self.root/'existing'; existing.mkdir()
        with self.assertRaises(FileExistsError): rename_directory(self.folder,'existing')
        self.assertTrue(existing.is_dir())
        for name in ('../bad','','.','destination'):
            with self.assertRaises(ValueError): rename_directory(self.folder,name)
        renamed=rename_directory(self.folder,'new folder')
        self.assertEqual((renamed/'child').read_text(),'keep')
        self.assertFalse(self.folder.exists())

    def test_compress_directory_contents_empty_folders_and_symlinks(self):
        tree=self.root/'project'; tree.mkdir()
        (tree/'empty').mkdir(); (tree/'.hidden').write_text('hidden')
        (tree/'nested').mkdir(); (tree/'nested'/'file.txt').write_text('contents')
        (tree/'outside').symlink_to(self.folder,target_is_directory=True)
        archive=compress_file(tree)
        with zipfile.ZipFile(archive) as output:
            self.assertIn('project/empty/',output.namelist())
            self.assertEqual(output.read('project/nested/file.txt'),b'contents')
            self.assertEqual(output.read('project/.hidden'),b'hidden')
            self.assertEqual(output.read('project/outside'),str(self.folder).encode())
            self.assertFalse(any(name.startswith('project/outside/') for name in output.namelist()))
        with self.assertRaises(FileExistsError): compress_file(tree)

    def test_directory_compress_menu(self):
        nav=Navigator.__new__(Navigator); nav.menu=Mock(return_value=6)
        with patch.object(nav,'compress_with_progress',return_value=self.root/'destination.zip',create=True) as compress:
            nav.directory_actions(self.folder)
            compress.assert_called_once_with(self.folder)
        self.assertIn('destination.zip',nav.message)

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

    def test_cancel_and_scp_form_do_not_change_file(self):
        navigator=Navigator(Mock())
        navigator.scp_file=Mock()
        for choice in (None,3,10):
            navigator.menu=Mock(return_value=choice); navigator.file_actions(self.source)
            self.assertEqual(self.source.read_text(),'preserve content')
        navigator.scp_file.assert_called_once_with(self.source)

if __name__=='__main__': unittest.main()
