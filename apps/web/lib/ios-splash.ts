// iPhone classes (CSS px + device pixel ratio, portrait) that get an iOS
// startup image. iOS 16.4+ only (browserslist), so nothing before the
// iPhone SE 2. Shared by the <head> of app/[locale]/layout.tsx (one
// <link rel="apple-touch-startup-image"> each) and scripts/gen-ios-splash.mjs
// (which renders public/icons/splash/<w>x<h>@<r>x.png at w*r by h*r pixels).
export const IOS_SPLASH = [
  { w: 440, h: 956, r: 3 }, // 16 Pro Max, 17 Pro Max
  { w: 430, h: 932, r: 3 }, // 14 Pro Max, 15 Plus, 15 Pro Max, 16 Plus
  { w: 402, h: 874, r: 3 }, // 16 Pro, 17
  { w: 393, h: 852, r: 3 }, // 14 Pro, 15, 15 Pro, 16
  { w: 428, h: 926, r: 3 }, // 12 Pro Max, 13 Pro Max, 14 Plus
  { w: 390, h: 844, r: 3 }, // 12, 13, 14, 16e
  { w: 375, h: 812, r: 3 }, // X, XS, 11 Pro, 12 mini, 13 mini
  { w: 414, h: 896, r: 3 }, // XS Max, 11 Pro Max
  { w: 414, h: 896, r: 2 }, // XR, 11
  { w: 375, h: 667, r: 2 }, // SE 2, SE 3
] as const;
