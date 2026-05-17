"""Upload to Vector Store accordion component."""

import gradio as gr
from app.ui.actions import handle_file_upload
from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)


def create_upload_accordion(
    document_processor,
) -> tuple[gr.Accordion, gr.Button, gr.Textbox]:
    """
    Create the upload accordion component.

    Args:
        document_processor: Document processor instance

    Returns:
        Tuple of (accordion component, upload button, upload status textbox)
    """

    async def handle_file_upload_wrapper(files):
        async for status in handle_file_upload(files, document_processor):
            yield status

    with gr.Accordion('Upload to Vector Store', open=False) as accordion:
        file_upload = gr.File(
            label='Upload PDF Documents',
            file_types=['.pdf'],
            file_count='multiple',
            type='filepath',
        )
        upload_button = gr.Button('Process Files', variant='primary')
        upload_status = gr.Textbox(label='Upload Status', interactive=False)

        upload_button.click(
            fn=handle_file_upload_wrapper,
            inputs=[file_upload],
            outputs=[upload_status],
            show_progress=True,
            queue=True,
        ).then(
            lambda: None,
            None,
            [file_upload],
        )

    return accordion, upload_button, upload_status
