from PyQt6.QtWidgets import QDialogButtonBox


def style_dialog_buttons(button_box: QDialogButtonBox) -> None:
    primary_buttons = {
        QDialogButtonBox.StandardButton.Save,
        QDialogButtonBox.StandardButton.Ok,
        QDialogButtonBox.StandardButton.Yes,
    }
    for button in button_box.buttons():
        variant = (
            "primary"
            if button_box.standardButton(button) in primary_buttons
            else "secondary"
        )
        button.setProperty("variant", variant)
