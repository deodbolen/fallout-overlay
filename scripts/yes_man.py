"""Yes Man server configuration and plain chat transport."""
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from ssh_manager import config_dir, atomic_json

APP={'name':'Yes Man','path':'builtin:yes-man','builtin':'yes-man','terminal':True,'exec':''}
DEFAULT={'protocol':'OpenAI compatible','url':'http://localhost:11434/v1','model':'','api_key':''}
SYSTEM='You are Yes Man, a cheerful, helpful assistant in a RobCo terminal. Be clear and honest about uncertainty. You can only chat; do not claim to run commands or access files.'


def settings():
    try:
        data=json.loads((config_dir()/'yes-man.json').read_text())
        return {key:data.get(key,value) if isinstance(data.get(key,value),str) else value for key,value in DEFAULT.items()}
    except (OSError,ValueError,AttributeError): return dict(DEFAULT)


def validate(config):
    config={key:str(config.get(key,value)).strip() for key,value in DEFAULT.items()}
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


def reply(config,messages):
    config=validate(config)
    base=config['url'].rstrip('/')
    ollama=config['protocol']=='Ollama'
    endpoint=base+('/chat' if base.endswith('/api') else '/api/chat') if ollama else base+('/chat/completions' if base.endswith('/v1') else '/v1/chat/completions')
    payload={'model':config['model'],'messages':[{'role':'system','content':SYSTEM}]+messages,'stream':False}
    headers={'Content-Type':'application/json','Accept':'application/json'}
    if config['api_key']: headers['Authorization']='Bearer '+config['api_key']
    request=Request(endpoint,data=json.dumps(payload).encode(),headers=headers,method='POST')
    try:
        with build_opener(NoRedirect()).open(request,timeout=90) as response:
            raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024: raise ValueError('Server reply is too large.')
        data=json.loads(raw)
        content=data['message']['content'] if ollama else data['choices'][0]['message']['content']
        if not isinstance(content,str) or not content.strip(): raise ValueError('Server returned an empty reply.')
        return content
    except HTTPError as error:
        raise ValueError('Server returned HTTP '+str(error.code)+'. Check the server address, model, and API key.') from None
    except (URLError,TimeoutError,OSError): raise ValueError('Could not reach the LLM server. Check its address and connection.') from None
    except (KeyError,IndexError,TypeError,json.JSONDecodeError): raise ValueError('Unexpected server response. Check the server type and model.') from None
