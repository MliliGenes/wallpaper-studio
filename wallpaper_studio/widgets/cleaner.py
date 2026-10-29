"""Desktop controls for the allowlisted home cache cleaner."""
from ..cleaner import CleanerModel
from ..components import Button, Column, Row, Text, component, use_model


@component
def Cleaner(config):
    model = use_model(CleanerModel, key='cleaner')
    status, busy = model.view()
    return Column(
        Text('HOME CLEANER', class_name='widget-label', align='start'),
        Text(status, wrap=True, max_width_chars=36, align='start'),
        Text('Close VS Code and Firefox first.', wrap=True, max_width_chars=36),
        Row(Button('Scan', on_click=model.start, sensitive=not busy),
            Button('Clean caches', on_click=lambda: model.start(True), sensitive=not busy), spacing=8),
        spacing=12, class_name='system-card',
    )
