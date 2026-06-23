package org.util;

/**
 * A lightweight utility to show progress in the console with a simple dot animation.
 */
public class ConsoleProgressMonitor implements AutoCloseable {
    private final String label;
    private final Thread thread;
    private volatile boolean running = true;

    public ConsoleProgressMonitor(String label) {
        this.label = label;
        System.out.print("\r" + label + "..."); // Show immediate feedback
        System.out.flush();
        this.thread = new Thread(() -> {
            int dots = 0;
            try {
                while (running) {
                    StringBuilder sb = new StringBuilder("\r").append(label);
                    for (int i = 0; i < dots; i++) {
                        sb.append(".");
                    }
                    // Add spaces to clear previous longer lines if necessary
                    sb.append("    "); 
                    System.out.print(sb.toString());
                    System.out.flush();
                    dots = (dots + 1) % 4;
                    Thread.sleep(400);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        });
        this.thread.setDaemon(true);
        this.thread.start();
    }

    /**
     * Stops the animation and replaces the line with a final message.
     */
    public void stop(String finalMessage) {
        running = false;
        thread.interrupt();
        // Move to start of line, print final message, then multiple spaces to clear, then newline
        System.out.print("\r" + finalMessage + "                                \n");
        System.out.flush();
    }

    @Override
    public void close() {
        if (running) {
            stop(label + " - Done.");
        }
    }
    
    public static void printHeader(String title) {
        String bar = "==========================================================";
        System.out.println("\n" + bar);
        System.out.println("   " + title);
        System.out.println(bar);
    }
}
