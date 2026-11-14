# नेपाली रेडियो — Android APK

यो फोल्डरका फाइलहरू GitHub मा राख्नुहोस्। `main` मा push गर्नासाथ GitHub ले आफैँ APK बनाउँछ।

## फाइल संरचना
- `www/index.html` — तपाईँको एप (nepali-radio-v43.html)
- `capacitor.config.json` — एपको नाम, ID, सेटिङ
- `package.json` — आवश्यक प्याकेज
- `.github/workflows/build-apk.yml` — APK बनाउने स्वचालित काम

## एप अपडेट गर्दा
`www/index.html` लाई नयाँ HTML ले बदल्नुहोस् र commit गर्नुहोस्। APK आफैँ फेरि बन्छ।
