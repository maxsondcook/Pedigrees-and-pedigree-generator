import "./globals.css";
import AppFrame from "../components/AppFrame";

export const metadata = {
  title: "Crossr",
  description: "Stallion search, hypomating, and sales intelligence.",
  icons: { icon: "/logo.png" },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AppFrame>{children}</AppFrame>
      </body>
    </html>
  );
}
