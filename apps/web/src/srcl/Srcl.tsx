"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import styles from "./Srcl.module.css";

// Adapted from the MIT-licensed SRCL components at sacred.computer.
export function Window({ title, tag = "SYS", className = "", children }: { title: string; tag?: string; className?: string; children: ReactNode }) {
  return (
    <section className={`${styles.window} ${className}`} aria-label={title}>
      <header className={styles.windowBar}><span>{title}</span><span>{tag}</span></header>
      <div className={styles.windowBody}>{children}</div>
    </section>
  );
}

export function Button({ theme = "secondary", className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { theme?: "primary" | "secondary" | "danger" }) {
  return <button className={`${styles.button} ${styles[theme]} ${className}`} {...props}>{children}</button>;
}

export function Input({ label, className = "", ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return <label className={`${styles.field} ${className}`}><span>{label}</span><input {...props}/></label>;
}

export function TextArea({ label, className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string }) {
  return <label className={`${styles.field} ${className}`}><span>{label}</span><textarea {...props}/></label>;
}

export function Select({ label, className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return <label className={`${styles.field} ${className}`}><span>{label}</span><select {...props}>{children}</select></label>;
}

export function Progress({ value }: { value: number }) {
  return <div className={styles.progress} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)}><i style={{ width: `${Math.max(0, Math.min(100, value))}%` }}/></div>;
}
