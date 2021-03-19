# GIPHY GIF integration

This page documents the server-level configuration required to enable
GIPHY integration to [add GIFs in your message](https://zulip.com/help/add-gifs-in-your-message) on a self-hosted Zulip server.

To enable this integration, you need to get a production API key from [GIPHY](https://developers.giphy.com/).

## Apply for API key

1. Create a GIPHY API Key by clicking “Create an App” on the
   [Developer Dashboard](https://developers.giphy.com/dashboard/) (you need to create an account first).

1. Choose **SDK** as product type and click **Next Step**.

1. Enter a name and a description for your app and click on
   **Create New App**.

1. You will receive a beta API key. Apply for a production API key
   by following the steps mentioned by GIPHY on the same page.

1. Copy the API key to be used below.

You can then configure your Zulip server to use GIPHY API as
follows:

1. In `/etc/zulip/zulip-secrets.conf`, set `giphy_api_key` as the
   GIPHY API key you just copied.

1. Restart the Zulip server with
   `/home/zulip/deployments/current/scripts/restart-server`.

This should enable GIPHY support in your server.
See [add GIFs in your message](https://zulip.com/help/add-gifs-in-your-message) for instructions on using it and troubleshooting information.
