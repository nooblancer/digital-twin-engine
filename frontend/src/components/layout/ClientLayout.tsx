"use client";

import { LayoutGroup } from "framer-motion";
import { PageTransition } from "./PageTransition";

/**
 * ClientLayout — client-side layout wrapper that provides:
 * - framer-motion LayoutGroup for shared layout animations across persistent elements (Req 12.2)
 * - PageTransition for cross-fade route animations
 *
 * This component is the client boundary between the server-rendered RootLayout
 * and the animated page content.
 *
 * Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
 */
export function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <LayoutGroup>
      <PageTransition>{children}</PageTransition>
    </LayoutGroup>
  );
}
