/* Loaded only by the Fallout LightDM GTK greeter launcher. Authentication
 * remains entirely with LightDM; we observe its result, never credentials. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <lightdm.h>
#include <gst/gst.h>

#define CANCELLED "fallout-auth-cancelled"

__attribute__((constructor)) static void greeter_only(void)
{
    /* The library is already loaded; do not inject it into greeter children. */
    unsetenv("LD_PRELOAD");
}

static void authentication_complete(LightDMGreeter *greeter, gpointer unused)
{
    (void) unused;
    gboolean cancelled = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(greeter), CANCELLED));
    g_object_set_data(G_OBJECT(greeter), CANCELLED, NULL);
    if (cancelled)
        return;
    if (!gst_init_check(NULL, NULL, NULL))
        return;
    GstElement *player = gst_element_factory_make("playbin", NULL);
    if (!player)
        return;
    const char *file = lightdm_greeter_get_is_authenticated(greeter)
        ? "file:///usr/share/fallout-ui/login-sounds/good.wav"
        : "file:///usr/share/fallout-ui/login-sounds/bad.wav";
    g_object_set(player, "uri", file, "volume", 0.85, NULL);
    GstBus *bus = gst_element_get_bus(player);
    if (gst_element_set_state(player, GST_STATE_PLAYING) != GST_STATE_CHANGE_FAILURE) {
        /* Finish the short cue before LightDM tears down the greeter on success.
         * Missing audio hardware must never prevent login. */
        GstMessage *message = gst_bus_timed_pop_filtered(bus, 2 * GST_SECOND,
            GST_MESSAGE_EOS | GST_MESSAGE_ERROR);
        if (message)
            gst_message_unref(message);
    }
    gst_element_set_state(player, GST_STATE_NULL);
    gst_object_unref(bus);
    gst_object_unref(player);
}

LightDMGreeter *lightdm_greeter_new(void)
{
    LightDMGreeter *(*original)(void) = dlsym(RTLD_NEXT, "lightdm_greeter_new");
    /* The launcher only loads us into the native GTK greeter. */
    if (!original)
        return NULL;
    LightDMGreeter *greeter = original();
    if (greeter)
        g_signal_connect(greeter, "authentication-complete",
                         G_CALLBACK(authentication_complete), NULL);
    return greeter;
}

gboolean lightdm_greeter_cancel_authentication(LightDMGreeter *greeter, GError **error)
{
    gboolean (*original)(LightDMGreeter *, GError **) =
        dlsym(RTLD_NEXT, "lightdm_greeter_cancel_authentication");
    if (!original)
        return FALSE;
    gboolean result = original(greeter, error);
    if (result)
        g_object_set_data(G_OBJECT(greeter), CANCELLED, GINT_TO_POINTER(TRUE));
    return result;
}
