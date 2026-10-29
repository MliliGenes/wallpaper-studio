"""An editable text card: pass title and text through layout.json props."""
from ..components import Column, Text, component


@component
def Notes(config, title="Notes", text="Your desktop, your way.\n\nTurn on Arrange widgets to move and resize these cards."):
    return Column(
        Text(title.upper(), class_name="widget-label", align="start"),
        Text(text, class_name="notes-text", align="start", wrap=True, max_width_chars=25),
        spacing=12,
        class_name="notes-card",
    )
