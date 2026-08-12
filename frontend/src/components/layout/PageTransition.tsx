"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { usePrefersReducedMotion } from "@/lib/animations";

/**
 * PageTransition — wraps page content with framer-motion AnimatePresence for
 * smooth cross-fade transitions between routes.
 *
 * - Uses `mode="wait"` so outgoing page exits before incoming page enters
 * - Cross-fade duration: 300ms (within the 200-400ms spec range)
 * - Resets scroll position to top on each page entry
 * - Respects `prefers-reduced-motion`: instant switch, no animation
 * - Navigation remains clickable during transitions (no pointer-events blocking)
 *
 * Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
 */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const prefersReducedMotion = usePrefersReducedMotion();

  // Reset scroll position to top on route change (Req 12.6)
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  // Reduced motion: render children immediately without animation (Req 12.4)
  if (prefersReducedMotion) {
    return <>{children}</>;
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={pathname}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.3, ease: "easeInOut" }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
