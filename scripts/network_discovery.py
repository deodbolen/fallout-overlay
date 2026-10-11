"""Asynchronous desktop network browsing, with bounded discovery requests."""
import threading
import time
from urllib.parse import urlsplit


def browse_uri(value):
    parsed=urlsplit(value)
    if parsed.scheme not in ('network','smb','dns-sd') or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid network discovery location.')
    return value


def discovered_servers(items):
    """Exclude generic network/workgroup shortcuts from discovered servers."""
    result=[]
    for item in items:
        uri=item.get('uri','')
        parsed=urlsplit(uri)
        if (parsed.scheme=='smb' and parsed.hostname) or (parsed.scheme=='dns-sd' and '_smb._tcp' in uri):
            result.append(item)
    return result


class Discovery:
    def __init__(self,window):
        self.window=window
        self.cache={}

    def browse(self,uri,refresh=False):
        from gi.repository import Gio,GLib,Gtk
        uri=browse_uri(uri)
        state=self.cache.setdefault(uri,{'items':[],'loading':False,'error':'','updated':0})
        if not state['loading'] and (refresh or time.monotonic()-state['updated']>30):
            state.update(loading=True,error='')
            location=Gio.File.new_for_uri(uri)
            cancel=Gio.Cancellable()
            timer=threading.Timer(10,cancel.cancel); timer.daemon=True
            def finish(items,error):
                timer.cancel()
                state.update(items=items,loading=False,error=error,updated=time.monotonic())
                return False
            def scan():
                timer.start()
                items=[]; error=''; enumerator=None
                try:
                    enumerator=location.enumerate_children('standard::name,standard::display-name,standard::target-uri',Gio.FileQueryInfoFlags.NONE,cancel)
                    while len(items)<200:
                        info=enumerator.next_file(cancel)
                        if info is None: break
                        target=info.get_attribute_string('standard::target-uri') or location.get_child(info.get_name()).get_uri()
                        scheme=urlsplit(target).scheme
                        if scheme not in ('smb','network','dns-sd'): continue
                        if scheme=='dns-sd' and '_smb._tcp' not in target: continue
                        items.append({'name':info.get_display_name(),'uri':target})
                except GLib.Error as exc: error=exc.message
                finally:
                    if enumerator:
                        try: enumerator.close(None)
                        except GLib.Error: pass
                items.sort(key=lambda item:item['name'].casefold())
                GLib.idle_add(finish,items,error)
            def mounted(source,result):
                try: source.mount_enclosing_volume_finish(result)
                except GLib.Error as exc:
                    if not any(exc.matches(Gio.io_error_quark(),code) for code in (Gio.IOErrorEnum.ALREADY_MOUNTED,Gio.IOErrorEnum.NOT_SUPPORTED)):
                        finish([],exc.message); return
                threading.Thread(target=scan,daemon=True).start()
            operation=Gtk.MountOperation.new(self.window)
            operation.set_password_save(Gio.PasswordSave.NEVER)
            location.mount_enclosing_volume(Gio.MountMountFlags.NONE,operation,cancel,mounted)
        # The RPC envelope reserves 'error' for failed requests.
        return {'items':state['items'],'loading':state['loading'],'message':state['error']}
