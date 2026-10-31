"""An editable text card: pass title and text through layout.json props."""
from ..components import Column, Text, component


@component
def Notes(config, title="Notes", text="To be is To do.\n\nDo something with your life, find passion, find love, get busy."):
    return Column(
        Text(title.upper(), class_name="widget-label", align="start"),
        Text(text, class_name="notes-text", align="start", wrap=True, max_width_chars=25),
        spacing=12,
        class_name="notes-card",
    )
