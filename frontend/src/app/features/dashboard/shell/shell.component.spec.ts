import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BreakpointObserver } from '@angular/cdk/layout';
import { of } from 'rxjs';
import { ShellComponent } from './shell.component';

describe('ShellComponent', () => {
  let component: ShellComponent;
  let fixture: ComponentFixture<ShellComponent>;
  let breakpointObserverSpy: jasmine.SpyObj<BreakpointObserver>;

  beforeEach(async () => {
    breakpointObserverSpy = jasmine.createSpyObj('BreakpointObserver', ['observe']);
    breakpointObserverSpy.observe.and.returnValue(
      of({ matches: false, breakpoints: {}, mediaQuery: '', media: '' }),
    );

    await TestBed.configureTestingModule({
      imports: [ShellComponent],
      providers: [{ provide: BreakpointObserver, useValue: breakpointObserverSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(ShellComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialize with desktop mode by default', () => {
    fixture.detectChanges();
    expect(component.isMobile()).toBe(false);
    expect(component.sidenavMode()).toBe('side');
  });

  it('should switch to mobile mode when viewport is handset', () => {
    breakpointObserverSpy.observe.and.returnValue(
      of({ matches: true, breakpoints: {}, mediaQuery: '', media: '' }),
    );

    component.ngOnInit();
    fixture.detectChanges();

    expect(component.isMobile()).toBe(true);
    expect(component.sidenavMode()).toBe('over');
  });

  it('should close sidenav on mobile when link is clicked', () => {
    component.isMobile.set(true);
    fixture.detectChanges();
    fixture.whenStable().then(() => {
      const sidenav = component.sidenav;
      spyOn(sidenav, 'close');
      component.onSidebarLinkClicked();
      expect(sidenav.close).toHaveBeenCalled();
    });
  });

  it('should not close sidenav on desktop when link is clicked', () => {
    component.isMobile.set(false);
    fixture.detectChanges();
    fixture.whenStable().then(() => {
      const sidenav = component.sidenav;
      spyOn(sidenav, 'close');
      component.onSidebarLinkClicked();
      expect(sidenav.close).not.toHaveBeenCalled();
    });
  });
});
