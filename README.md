![Project Logo](custom_components/adaptive_lighting/icon.svg)
# Adaptive Lighting for Home Assistant

Automatically adjust the color temperature and brightness of your lights throughout the day to match natural lighting patterns and improve your circadian rhythm.

## Overview

Adaptive Lighting is a Home Assistant custom component that intelligently controls your smart lights based on the sun's position and time of day. It gradually transitions your lights from bright, cool white during the day to warm, dim lighting in the evening, helping maintain your natural sleep-wake cycle.

## Features

### 🌅 **Automatic Sun-Based Adjustments**
- **Brightness**: Automatically adjusts from 1% to 100% based on sun elevation
- **Color Temperature**: Transitions from warm 2200K to cool 6500K throughout the day
- **Smooth Transitions**: Gradual changes every 2 minutes with smooth 1-second transitions
- **Power-Safe Updates**: Brightness and color are sent sequentially for broad bulb compatibility, while a turn-off request immediately cancels the pending sequence
- **Native Matter and ZHA Control**: Uses power-neutral protocol commands and fails closed if that native path is temporarily unavailable

### 🌙 **Smart Night Mode**
- **Configurable Sleep Window**: Set your preferred bedtime and wake-up time
- **Gradual Wind-Down**: Lights start dimming 1 hour before your bedtime
- **Gentle Wake-Up**: Lights gradually brighten over 1 hour after your wake-up time
- **Minimum Night Lighting**: 1% brightness with warm 2200K during sleep hours

### 🎛️ **Intelligent Light Management**
- **Automatic Discovery**: Finds all compatible lights in your home
- **Turn-On Control**: Immediately applies appropriate settings when lights are turned on
- **Manual Override Protection**: Respects manual adjustments and temporarily stops automation
- **Selective Control**: Exclude specific lights from adaptive control

### ⚙️ **Easy Configuration**
- **Time Selectors**: User-friendly hour/minute pickers for sleep schedule
- **Entity Selection**: Visual interface to exclude specific lights
- **Real-Time Updates**: Changes apply immediately without restarting

## How It Works

### Daily Light Cycle
1. **Dawn to Day** (Low to High Sun): Brightness increases from 1% to 100%, color temperature cools from 2200K to 6500K
2. **Daytime** (High Sun): Maximum brightness (100%) with cool daylight (6500K)
3. **Evening Transition** (1 hour before bedtime): Gradual dimming from current brightness to 1%
4. **Night Mode** (Bedtime to Wake-up): Minimum brightness (1%) with warm light (2200K)
5. **Morning Transition** (1 hour after wake-up): Gradual brightening from 1% to 100%

### Smart Behavior
- **Turn-On Events**: When you turn on a light, it immediately applies the current adaptive settings
- **Power Intent Protection**: A recent turn-off takes precedence over delayed or bouncing `on` state reports
- **Manual Adjustments**: If you manually change brightness or color, the system temporarily stops controlling that light
- **Automatic Reset**: Manual override is cleared when the light is turned off and on again
- **Restart-Safe State**: The enable switch and active manual holds survive Home Assistant restarts

## Installation

### HACS (Recommended)
1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the "+" button and search for "Adaptive Lighting"
4. Install the integration
5. Restart Home Assistant

### Manual Installation
1. Download the latest release
2. Copy the `adaptive_lighting` folder to your `custom_components` directory
3. Restart Home Assistant
4. Go to Configuration → Integrations
5. Click "+" and search for "Adaptive Lighting"

## Configuration

### Initial Setup
1. Go to **Configuration** → **Integrations**
2. Click **"+ Add Integration"**
3. Search for **"Adaptive Lighting"**
4. Configure your settings:
   - **Night Start Time**: When your sleep period begins (lights reach minimum)
   - **Night End Time**: When your sleep period ends (lights start brightening)
   - **Exclude Entities**: Lights you want to control manually

### Settings Explained

| Setting | Description | Default |
|---------|-------------|---------|
| Night Start Time | When night mode begins (minimum brightness) | 22:00 |
| Night End Time | When night mode ends (brightening starts) | 06:30 |
| Exclude Entities | Lights to exclude from adaptive control | None |

### Transition Timeline Example
If Night Start = 22:00 and Night End = 06:30:
- **21:00-22:00**: Gradual dimming from current brightness to 1%
- **22:00-06:30**: Night mode (1% brightness, 2200K)
- **06:30-07:30**: Gradual brightening from 1% to 100%

## Compatible Lights

Adaptive Lighting works with any Home Assistant light entity that supports:
- **Brightness control** (required)
- **Color temperature** (preferred) OR **RGB color** (fallback)

### Supported Light Types
- Matter lights (native power-neutral commands)
- Zigbee lights connected through ZHA (native power-neutral commands)
- Zigbee2MQTT lights (Home Assistant service fallback)
- Philips Hue
- LIFX
- Z-Wave lights
- WiFi smart bulbs (Tuya, TP-Link Kasa, etc.)
- Any other lights with brightness and color support

## Advanced Usage

### Single Instance
Adaptive Lighting uses one global controller. Home Assistant prevents adding a second
instance so two schedules cannot send competing commands to the same bulbs. Use
**Exclude Entities** to leave selected lights under another automation's control.

### Integration with Other Automations
Adaptive Lighting works alongside your existing automations:
- Manual brightness/color changes temporarily override adaptive control
- Turning lights off and on again re-enables adaptive control
- Use Home Assistant scenes and automations normally

## Troubleshooting

### Lights Not Responding
- Ensure lights support brightness control
- Check that lights aren't in the exclude list
- Verify lights are turned on
- Restart Home Assistant to reload the component

### Manual Changes Not Respected
- Native Matter/ZHA feedback is allowed to settle before a manual override is confirmed
- A stable value which differs from the requested adaptive value starts a two-hour hold
- Turn the light off and on to reset manual override

### Configuration Not Saving
- Restart Home Assistant after installing
- Clear browser cache if UI doesn't update
- Check Home Assistant logs for error messages

## Technical Details

### Update Frequency
- **Periodic Updates**: Every 2 minutes
- **Transition Duration**: 1 second per change
- **Command Ordering**: Brightness completes before color temperature is sent
- **Turn-On Response**: Immediate

### Apple Home comparison
Apple HomeKit Adaptive Lighting can install a multi-point color-temperature curve on
compatible accessories. Standard Matter and Zigbee light clusters do not expose an
equivalent generic 24-hour curve upload. This integration therefore uses short native
updates rather than persistent device-side transitions.

Matter lights receive `MoveToLevel` and `MoveToColorTemperature` commands, and ZHA
lights receive the equivalent Zigbee ZCL commands. These commands explicitly set
`ExecuteIfOff` to false, so they cannot turn an off light on. Brightness and color
temperature remain separate sequential commands for bulbs which discard one attribute
when both arrive together. Avoiding overlapping long transitions also works around
bulb firmware which can otherwise become unresponsive until power-cycled.

Turn-on commands issued by another Matter fabric are visible to Home Assistant only
through the resulting state reports. If such a report arrives during the short
turn-off race guard, a resolved native target is adapted immediately: its
`ExecuteIfOff=false` commands are safe even if the `on` report is stale. Only generic
service targets retain the five-second confirmation. Native brightness/color reports
are matched to a command generation and reconciled after they settle. Intermediate
transition reports do not start a hold, while a stable divergent Apple Home setting
does. Availability recovery (`unavailable`/`unknown` to `on`) is not treated as a power
cycle and therefore cannot silently release an existing hold.

For Zigbee2MQTT, Philips Hue, Z-Wave, Wi-Fi, and other non-native integrations, the
integration retains the generic `light.turn_on` path. That fallback cancels adaptation
as soon as `light.turn_off` is requested and checks the power state between commands.
Recognized Matter/ZHA entities never fall through to this power-changing service when
their native client, endpoint, or required cluster is unavailable; that update is
skipped and retried later. RGB-only Matter/ZHA entities are likewise skipped until a
power-neutral native color command is implemented. Home Assistant light groups are
observed for user power intent but excluded as write targets, preventing an on group
from powering up members which were intentionally off.

### Color Calculations
- **Sun Elevation**: Uses Home Assistant's sun integration
- **Brightness Formula**: Linear interpolation based on sun angle (-6° to +30°)
- **Color Temperature**: Linear interpolation based on sun angle (-6° to +60°)
- **RGB Fallback**: CCT to RGB conversion for lights without color temperature support

## Contributing

Contributions are welcome! Please feel free to submit pull requests, report bugs, or suggest features.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Changelog

### Version 1.0.0
- Initial release
- Sun-based brightness and color temperature adjustment
- Configurable sleep schedule with transition periods
- Manual override detection
- Smart turn-on control
- User-friendly configuration interface

### Version 1.3.1
- Removed experimental long device-side transitions because some bulbs became unresponsive
- Retained short, power-neutral Matter and ZHA commands every 2 minutes
- Retained sequential brightness and color-temperature delivery

### Version 1.3.2
- Added delayed confirmation for quick cross-fabric off/on cycles

### Version 1.3.3
- Fail closed when native Matter/ZHA resolution is unavailable
- Exclude Home Assistant light groups from adaptive writes
- Preserve manual holds across availability recovery and Home Assistant restarts
- Reconcile stable foreign-fabric changes against native command generations
- Restore the integration enable switch after restart and enforce one global instance

### Version 1.3.4
- Apply native Matter/ZHA settings immediately after a cross-fabric off/on cycle
- Retain the five-second safety confirmation for generic service fallbacks

---

**Enjoy better lighting that adapts to your natural rhythm! 🌞🌙**
