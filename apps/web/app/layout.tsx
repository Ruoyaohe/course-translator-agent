import "./styles.css";

export const metadata = {
  title: "NTU Course Agent",
  description: "课堂同传、纪要、脑图与 Obsidian 发布",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "NTU Agent" },
};

export const viewport = { width: "device-width", initialScale: 1, viewportFit: "cover", themeColor: "#11100e" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}

