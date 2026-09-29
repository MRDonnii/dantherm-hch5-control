"""What each WebUI role may do.

Kept separate from the HTTP handler so the rules are easy to read and test.
"""

# Everyday controls on the overview page. A plain user may change these and
# nothing else in the controller configuration.
USER_CONFIG_KEYS = frozenset({
    "mode", "manual_level", "local_normal_level", "quick_boost_minutes",
    "bypass", "cooling_enabled", "fireplace", "fireplace_minutes",
    "afterheat_enabled", "afterheat_setpoint", "standby_minutes", "bonfire_minutes",
    # Week planner and holiday are household routines, not technical setup.
    "schedule_enabled", "schedule_periods", "vacation_enabled", "vacation_level",
    "vacation_from", "vacation_until",
})

# Read-only or harmless admin-helper actions a plain user may trigger.
USER_ADMIN_ACTIONS = frozenset({
    "check_update", "get_update_status", "get_update_channel",
    "get_system_status", "get_filter_config", "reset_filter",
})

CAPABILITIES = {
    # Daily operation of the unit.
    "control": {"admin", "technician", "user"},
    # Advanced controller settings (sensors, profiles, automation, sizing ...).
    "configure": {"admin", "technician"},
    # Diagnostics report, sniffer, raw data, technique/system pages.
    "diagnostics": {"admin", "technician"},
    # Pi actions: restart, reboot, Wi-Fi, updates, power profile.
    "system": {"admin", "technician"},
    # SMTP settings and alarm mails.
    "mail": {"admin", "technician"},
    # Create, change and delete users.
    "users": {"admin"},
    # Turn the login requirement on or off.
    "login_switch": {"admin"},
}


def can(role, capability):
    return role in CAPABILITIES.get(capability, ())


def capabilities(role):
    return sorted(name for name, roles in CAPABILITIES.items() if role in roles)


def config_allowed(role, patch):
    """Return the keys in ``patch`` the role may not change (empty = allowed)."""
    if can(role, "configure"):
        return []
    return sorted(key for key in patch if key not in USER_CONFIG_KEYS)


def admin_action_allowed(role, action):
    return can(role, "system") or action in USER_ADMIN_ACTIONS
