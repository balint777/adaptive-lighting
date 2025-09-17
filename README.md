![Project Logo](custom_components/adaptive_lighting/icon.svg)
# Adaptive Lighting for Home Assistant

Automatically adjust the color temperature and brightness of your lights throughout the day to match natural lighting patterns and improve your circadian rhythm.

## Overview

Adaptive Lighting is a Home Assistant custom component that intelligently controls your smart lights based on the sun's position and time of day. It gradually transitions your lights from bright, cool white during the day to warm, dim lighting in the evening, helping maintain your natural sleep-wake cycle.

## Features

### 🌅 **Automatic Sun-Based Adjustments**
- **Brightness**: Automatically adjusts from 1% to 100% based on sun elevation
- **Color Temperature**: Transitions from warm 2200K to cool 6500K throughout the day
- **Smooth Transitions**: Gradual changes every 2 minutes with smooth 2-second transitions

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
- **Manual Adjustments**: If you manually change brightness or color, the system temporarily stops controlling that light
- **Automatic Reset**: Manual override is cleared when the light is turned off and on again

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
- Philips Hue
- LIFX
- Zigbee lights (via ZHA/Zigbee2MQTT)
- Z-Wave lights
- WiFi smart bulbs (Tuya, TP-Link Kasa, etc.)
- Any other lights with brightness and color support

## Advanced Usage

### Multiple Instances
You can create multiple Adaptive Lighting instances for different areas:
1. Create separate instances with different settings
2. Use the "Exclude Entities" feature to assign lights to specific instances
3. Perfect for having different sleep schedules in different rooms

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
- Manual override detection has a 1-second grace period
- Very rapid changes might not be detected as manual
- Turn the light off and on to reset manual override

### Configuration Not Saving
- Restart Home Assistant after installing
- Clear browser cache if UI doesn't update
- Check Home Assistant logs for error messages

## Technical Details

### Update Frequency
- **Periodic Updates**: Every 2 minutes
- **Transition Duration**: 2 seconds per change
- **Turn-On Response**: Immediate

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

---

**Enjoy better lighting that adapts to your natural rhythm! 🌞🌙**
