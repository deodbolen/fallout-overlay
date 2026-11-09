"""Yes Man server configuration and plain chat transport."""
import json
import ssl
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from urllib.error import HTTPError, URLError
from ssh_manager import config_dir, atomic_json

APP={'name':'Yes Man','path':'builtin:yes-man','builtin':'yes-man','terminal':True,'exec':''}
DEFAULT={'protocol':'OpenAI compatible','url':'http://localhost:11434/v1','model':'','api_key':'','verify_tls':True}
SYSTEM=Path(__file__).with_name('yes_man_prompt.txt').read_text(encoding='utf-8').strip()


def settings():
    try:
        data=json.loads((config_dir()/'yes-man.json').read_text())
        result={key:data.get(key,value) if isinstance(data.get(key,value),type(value)) else value for key,value in DEFAULT.items()}
        return result
    except (OSError,ValueError,AttributeError): return dict(DEFAULT)


def validate(config):
    verify_tls=config.get('verify_tls',True) is not False
    config={key:str(config.get(key,value)).strip() for key,value in DEFAULT.items() if key!='verify_tls'}
    config['verify_tls']=verify_tls
    parsed=urlsplit(config['url'])
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Enter an http:// or https:// server address without credentials, query, or fragment.')
    if any(ord(c)<32 for c in config['url']+config['api_key']): raise ValueError('Server address and API key cannot contain control characters.')
    if config['protocol'] not in ('OpenAI compatible','Ollama'): raise ValueError('Choose a supported server type.')
    if not config['model']: raise ValueError('Enter a model name installed on your server.')
    return config


def save(config): atomic_json(config_dir()/'yes-man.json',validate(config))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def endpoint(config):
    base=config['url'].rstrip('/')
    if config['protocol']=='Ollama':
        return base if base.endswith('/api/chat') else base+('/chat' if base.endswith('/api') else '/api/chat')
    if base.endswith('/chat/completions'): return base
    return base+('/chat/completions' if base.endswith('/v1') else '/v1/chat/completions')


def reply(config,messages):
    config=validate(config)
    target=endpoint(config)
    ollama=config['protocol']=='Ollama'
    payload={'model':config['model'],'messages':[{'role':'system','content':SYSTEM}]+messages,'stream':False}
    headers={'Content-Type':'application/json','Accept':'application/json'}
    if config['api_key']: headers['Authorization']='Bearer '+config['api_key']
    request=Request(target,data=json.dumps(payload).encode(),headers=headers,method='POST')
    try:
        handlers=[NoRedirect()]
        if not config['verify_tls']: handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
        with build_opener(*handlers).open(request,timeout=90) as response:
            raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024: raise ValueError('Server reply is too large.')
        data=json.loads(raw)
        content=data['message']['content'] if ollama else data['choices'][0]['message']['content']
        if not isinstance(content,str) or not content.strip(): raise ValueError('Server returned an empty reply.')
        return content
    except HTTPError as error:
        try:
            body=error.read(8192).decode('utf-8',errors='replace')
            try:
                detail=json.loads(body).get('error','')
                if isinstance(detail,dict): detail=detail.get('message','')
                if not isinstance(detail,str): detail=''
            except (ValueError,AttributeError): detail=''
            if config['api_key']: detail=detail.replace(config['api_key'],'[redacted]')
            detail=''.join(c for c in detail if c.isprintable())[:300]
        finally: error.close()
        raise ValueError('HTTP '+str(error.code)+' at '+target+('. '+detail if detail else '. Check address, server type, model and API key.')) from None
    except URLError as error:
        if isinstance(error.reason,ssl.SSLCertVerificationError):
            raise ValueError('TLS certificate verification failed. Trust the server certificate, or disable Verify TLS certificate for a trusted server (like curl -k).') from None
        raise ValueError('Could not reach '+target+'. Check its address and connection.') from None
    except (TimeoutError,OSError): raise ValueError('Could not reach the LLM server. Check its address and connection.') from None
    except (KeyError,IndexError,TypeError,json.JSONDecodeError): raise ValueError('Unexpected server response. Check the server type and model.') from None
