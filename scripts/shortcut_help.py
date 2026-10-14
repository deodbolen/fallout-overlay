"""Shortcut reference shared by the navigator and embedded terminal views."""


def text(section, modifier='ctrl', title='', context=''):
    global_keys = ['Ctrl+I   Show keyboard shortcuts',
                   'F12   Show / hide the overlay',
                   'Ctrl+Shift+B   Toggle transparent background']
    navigation = ['↑ / ↓ or J / K   Select an item', 'Enter   Open / select',
                  'Esc / Backspace   Back', 'Page Up / Page Down   Scroll items',
                  'Q   Exit the overlay']
    sections = {
        'HOME': ['P   Open the power menu', 'Tab   Focus the power button',
                 'Space / Enter   Activate the focused button'],
        'DATA': navigation + ['← / →   Change Data page', 'Ctrl+M or M   File menu',
                              'Ctrl+N   New file / directory', 'O   Open file or directory shell',
                              'S   Open a shell here', 'H   Show / hide hidden files'],
        'SSH': navigation + ['← / →   Switch Hosts / Keys'],
        'TERMINAL': navigation,
        'INV': navigation + ['← / →   Switch Tool Belt / Applications',
                             'Ctrl+M or M   Launch / add / remove a Tool Belt favorite'],
        'SETTINGS': navigation + ['+ / −   Adjust the selected font or volume setting'],
        'SESSION': ['Ctrl+]   Return to navigator', 'Ctrl+↑ / ↓   Switch sessions',
                    'Ctrl+Shift+W   Close session', 'Ctrl+Shift+C / V   Copy / paste',
                    'Ctrl+Shift+A   Select all', 'Shift+↑ / ↓   Select text',
                    'Enter   Return after a session has ended'],
    }
    if section != 'SESSION':
        global_keys.append(modifier.title() + '+← / →   Change section')
    body = 'GLOBAL SHORTCUTS\n' + '\n'.join(global_keys)
    body += '\n\n' + (title or section) + '\n' + '\n'.join(sections.get(section, navigation))
    if context:
        body += '\n\nCURRENT PAGE\n' + context
    return body
